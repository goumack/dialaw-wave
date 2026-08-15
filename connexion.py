"""Adaptation entre SQLite (poste local) et PostgreSQL (hébergement).

Le reste de l'application écrit ses requêtes une seule fois, en dialecte
SQLite. Ce module les traduit au vol quand la base est un PostgreSQL, ce qui
évite d'entretenir deux jeux de requêtes.

Le choix se fait sur la variable d'environnement DATABASE_URL :
    absente  -> SQLite, fichier local (développement, démarrage rapide)
    présente -> PostgreSQL distant (Neon), qui survit aux redéploiements

C'est ce second cas qui règle la remise à zéro des données : la base vit
hors du serveur web, donc elle n'est pas effacée quand celui-ci est reconstruit.
"""

import os
import re
import sqlite3

POSTGRES = "postgresql"
SQLITE = "sqlite"


def url_base() -> str:
    """Chaîne de connexion PostgreSQL, ou chaîne vide pour rester en SQLite."""
    url = (os.environ.get("DATABASE_URL") or "").strip()
    # Certains hébergeurs fournissent encore l'ancien préfixe « postgres:// »,
    # que psycopg refuse.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def moteur() -> str:
    return POSTGRES if url_base() else SQLITE


# ---------------------------------------------------------------------------
# Traduction du SQL
# ---------------------------------------------------------------------------

# Les chaînes littérales sont mises de côté avant traduction : un « ? » ou un
# « AUTOINCREMENT » à l'intérieur d'un texte ne doit jamais être réécrit.
_LITTERAL = re.compile(r"'(?:[^']|'')*'")

# Appliqués AVANT la mise à l'abri des littéraux : ces motifs contiennent
# eux-mêmes des chaînes ('now', 'localtime') qui seraient sinon masquées et
# donc jamais reconnues.
# Les horodatages sont stockés en TEXT (« 2026-08-09 22:15:30 ») pour rester
# lisibles et identiques sur les deux moteurs. PostgreSQL refusant de comparer
# du texte à un timestamp, la date calculée est reconvertie en texte au même
# format — la comparaison redevient alors lexicographique, donc chronologique.
_FORMAT_TEXTE = "'YYYY-MM-DD HH24:MI:SS'"

_DATES = (
    # datetime('now', 'localtime', ?) -> texte au même format
    (re.compile(r"datetime\(\s*'now'\s*,\s*'localtime'\s*,\s*\?\s*\)", re.I),
     f"to_char(NOW() + \x01::interval, {_FORMAT_TEXTE})"),
    (re.compile(r"datetime\(\s*'now'\s*,\s*'localtime'\s*\)", re.I),
     f"to_char(NOW(), {_FORMAT_TEXTE})"),
    (re.compile(r"datetime\(\s*'now'\s*\)", re.I),
     f"to_char(NOW(), {_FORMAT_TEXTE})"),
)

_REMPLACEMENTS = (
    # Clés primaires auto-incrémentées
    (re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", re.I), "SERIAL PRIMARY KEY"),
    # Insertion ignorée si la clé existe déjà
    (re.compile(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.I), "INSERT INTO"),
    # Données binaires : BLOB est propre à SQLite
    (re.compile(r"\bBLOB\b", re.I), "BYTEA"),
)


def _sans_litteraux(sql: str):
    """Extrait les chaînes SQL pour les protéger de la traduction."""
    gardes = []

    def remplacer(trouve):
        gardes.append(trouve.group(0))
        return f"\x00{len(gardes) - 1}\x00"

    return _LITTERAL.sub(remplacer, sql), gardes


def _restaurer(sql: str, gardes) -> str:
    for index, litteral in enumerate(gardes):
        sql = sql.replace(f"\x00{index}\x00", litteral)
    return sql


def traduire(sql: str) -> str:
    """Convertit une requête SQLite en PostgreSQL."""
    # Les fonctions de date d'abord : leurs arguments sont des littéraux
    # ('now', 'localtime') qui seraient masqués par l'étape suivante.
    for motif, remplacement in _DATES:
        sql = motif.sub(remplacement, sql)

    sql, gardes = _sans_litteraux(sql)

    for motif, remplacement in _REMPLACEMENTS:
        sql = motif.sub(remplacement, sql)

    # Marqueurs de paramètres : ? (SQLite) -> %s (psycopg).
    sql = sql.replace("?", "%s")
    # Le marqueur temporaire posé par _DATES devient un vrai paramètre
    sql = sql.replace("\x01", "%s")

    # « INSERT OR IGNORE » devenu « INSERT » : il lui faut sa clause finale
    if re.match(r"\s*INSERT\s+INTO\s+config\b", sql, re.I) and \
            "ON CONFLICT" not in sql.upper():
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT (cle) DO NOTHING"

    return _restaurer(sql, gardes)


# ---------------------------------------------------------------------------
# Connexions
# ---------------------------------------------------------------------------

class ConnexionPostgres:
    """Donne à psycopg l'interface de sqlite3 attendue par l'application.

    L'application appelle « connexion.execute(sql, params) » et lit les
    colonnes par leur nom ; psycopg passe normalement par un curseur et des
    marqueurs %s. Cette enveloppe absorbe la différence.
    """

    # Sans délai explicite, psycopg attend plus d'une minute avant d'abandonner :
    # l'hébergeur conclurait à un déploiement en échec, sans cause lisible.
    DELAI_CONNEXION = 10

    def __init__(self, url: str):
        import psycopg
        from psycopg.rows import dict_row

        self._connexion = psycopg.connect(
            url,
            row_factory=dict_row,
            autocommit=False,
            connect_timeout=self.DELAI_CONNEXION,
        )

    def execute(self, sql: str, parametres=()):
        curseur = self._connexion.cursor()
        try:
            curseur.execute(traduire(sql), tuple(parametres))
        except Exception:
            # PostgreSQL invalide toute la transaction après une erreur :
            # sans ce rollback, chaque requête suivante échouerait aussi, y
            # compris celles qui servent à afficher la page d'erreur.
            self._connexion.rollback()
            raise
        return curseur

    def executescript(self, script: str):
        """Joue un script multi-instructions, comme sqlite3.executescript."""
        for instruction in script.split(";"):
            if instruction.strip():
                self.execute(instruction)
        self._connexion.commit()

    def commit(self):
        self._connexion.commit()

    def rollback(self):
        self._connexion.rollback()

    def close(self):
        self._connexion.close()

    @property
    def brute(self):
        return self._connexion


def ouvrir(chemin_sqlite: str):
    """Ouvre la base : PostgreSQL si DATABASE_URL est définie, sinon SQLite."""
    url = url_base()
    if url:
        return ConnexionPostgres(url)

    connexion = sqlite3.connect(chemin_sqlite,
                                detect_types=sqlite3.PARSE_DECLTYPES)
    connexion.row_factory = sqlite3.Row
    connexion.execute("PRAGMA foreign_keys = ON")
    return connexion
