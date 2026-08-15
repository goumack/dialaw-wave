"""Couche d'accès aux données (SQLite, bibliothèque standard).

Aucune dépendance externe : le module sqlite3 est fourni avec Python.
Les valeurs de la colonne `statut` restent sans accent : ce sont des
identifiants techniques, traduits à l'affichage par le filtre `libelle_statut`.
"""

import secrets
from datetime import datetime

from flask import current_app, g
from werkzeug.security import generate_password_hash

import connexion as cx
from config import CONFIG_PAR_DEFAUT

# Alphabet sans caractères ambigus (ni 0/O, ni 1/I/L) : les codes sont dictés
# au téléphone ou recopiés à la main, il faut éviter toute confusion.
ALPHABET_CODE = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    cle    TEXT PRIMARY KEY,
    valeur TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    email             TEXT NOT NULL UNIQUE,
    mot_de_passe_hash TEXT NOT NULL,
    cree_le           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commandes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    reference          TEXT NOT NULL UNIQUE,
    nom                TEXT NOT NULL,
    telephone          TEXT NOT NULL,
    montant            INTEGER NOT NULL,
    statut             TEXT NOT NULL DEFAULT 'nouvelle',
    numero_wave_client TEXT,
    code_acces         TEXT UNIQUE,
    code_envoye        INTEGER NOT NULL DEFAULT 0,
    note               TEXT,
    cree_le            TEXT NOT NULL,
    paye_declare_le    TEXT,
    traite_le          TEXT,
    traite_par         TEXT
);

CREATE TABLE IF NOT EXISTS sessions_acces (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    commande_id  INTEGER NOT NULL,
    device_id    TEXT NOT NULL,
    ip           TEXT,
    user_agent   TEXT,
    cree_le      TEXT NOT NULL,
    derniere_vue TEXT NOT NULL,
    FOREIGN KEY (commande_id) REFERENCES commandes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fichiers (
    nom       TEXT PRIMARY KEY,
    type_mime TEXT NOT NULL,
    contenu   BLOB NOT NULL,
    cree_le   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tentatives (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ip       TEXT NOT NULL,
    appareil TEXT,
    code     TEXT,
    cree_le  TEXT NOT NULL
);
"""

# Les index sont créés APRÈS les migrations : un index posé sur une colonne
# ajoutée par ALTER TABLE échouerait s'il était joué en même temps que les
# CREATE TABLE, sur une base antérieure à cette colonne.
INDEX = """
CREATE INDEX IF NOT EXISTS idx_commandes_statut ON commandes(statut);
CREATE INDEX IF NOT EXISTS idx_commandes_code   ON commandes(code_acces);

CREATE UNIQUE INDEX IF NOT EXISTS idx_session_unique
    ON sessions_acces(commande_id, device_id);

CREATE INDEX IF NOT EXISTS idx_tentatives_ip  ON tentatives(ip, cree_le);
CREATE INDEX IF NOT EXISTS idx_tentatives_app ON tentatives(appareil, cree_le);
"""


# ---------------------------------------------------------------------------
# Connexion
# ---------------------------------------------------------------------------

def get_db():
    """Connexion réutilisée pendant toute la requête.

    PostgreSQL si DATABASE_URL est définie (la base survit alors aux
    redéploiements), SQLite sur fichier sinon.
    """
    if "db" not in g:
        g.db = cx.ouvrir(current_app.config["DATABASE"])
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    """Crée les tables, la configuration par défaut et le compte administrateur."""
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        _migrer(db)
        db.executescript(INDEX)

        for cle, valeur in CONFIG_PAR_DEFAUT.items():
            db.execute(
                "INSERT OR IGNORE INTO config (cle, valeur) VALUES (?, ?)",
                (cle, valeur),
            )

        email = app.config["ADMIN_EMAIL"]
        existe = db.execute(
            "SELECT 1 FROM admins WHERE email = ?", (email,)
        ).fetchone()
        if not existe:
            db.execute(
                "INSERT INTO admins (email, mot_de_passe_hash, cree_le) "
                "VALUES (?, ?, ?)",
                (
                    email,
                    generate_password_hash(app.config["ADMIN_MOT_DE_PASSE"]),
                    maintenant(),
                ),
            )
        db.commit()


def _migrer(db):
    """Ajoute les colonnes apparues après la première mise en production.

    CREATE TABLE IF NOT EXISTS ne modifie pas une table déjà créée : sans
    ceci, une base existante resterait dans l'ancien schéma.
    """
    colonnes_attendues = {
        "tentatives": {"appareil": "TEXT"},
    }
    for table, colonnes in colonnes_attendues.items():
        presentes = _colonnes_existantes(db, table)
        for nom, type_sql in colonnes.items():
            if nom not in presentes:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {type_sql}")
    db.commit()


def _colonnes_existantes(db, table: str) -> set:
    """Noms des colonnes d'une table, quel que soit le moteur.

    PRAGMA table_info est propre à SQLite ; PostgreSQL passe par le
    catalogue information_schema.
    """
    if cx.moteur() == cx.POSTGRES:
        lignes = db.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?", (table,)
        ).fetchall()
        return {ligne["column_name"] for ligne in lignes}

    return {
        ligne["name"]
        for ligne in db.execute(f"PRAGMA table_info({table})").fetchall()
    }


def maintenant():
    """Horodatage ISO à la seconde, sans microsecondes."""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


# ---------------------------------------------------------------------------
# Configuration (clé / valeur)
# ---------------------------------------------------------------------------

def lire_config():
    lignes = get_db().execute("SELECT cle, valeur FROM config").fetchall()
    valeurs = dict(CONFIG_PAR_DEFAUT)
    valeurs.update({l["cle"]: l["valeur"] for l in lignes})
    return valeurs


def enregistrer_fichier(nom: str, contenu: bytes, type_mime: str):
    """Stocke un fichier binaire en base plutôt que sur le disque.

    L'hébergement efface son disque à chaque déploiement : une affiche
    déposée dans un dossier disparaîtrait au prochain « git push ». En base,
    elle survit — comme les réglages et les commandes.
    """
    db = get_db()
    db.execute(
        "INSERT INTO fichiers (nom, type_mime, contenu, cree_le) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(nom) DO UPDATE SET type_mime = excluded.type_mime, "
        "contenu = excluded.contenu, cree_le = excluded.cree_le",
        (nom, type_mime, contenu, maintenant()),
    )
    db.commit()


def lire_fichier(nom: str):
    """Renvoie (contenu, type_mime) ou None si le fichier n'existe pas."""
    ligne = get_db().execute(
        "SELECT contenu, type_mime FROM fichiers WHERE nom = ?", (nom,)
    ).fetchone()
    if ligne is None:
        return None
    contenu = ligne["contenu"]
    # psycopg renvoie un memoryview, sqlite3 des octets : on uniformise
    return bytes(contenu), ligne["type_mime"]


def supprimer_fichier(nom: str):
    db = get_db()
    db.execute("DELETE FROM fichiers WHERE nom = ?", (nom,))
    db.commit()


def ecrire_config(valeurs: dict):
    db = get_db()
    for cle, valeur in valeurs.items():
        db.execute(
            "INSERT INTO config (cle, valeur) VALUES (?, ?) "
            "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
            (cle, str(valeur)),
        )
    db.commit()


# ---------------------------------------------------------------------------
# Commandes
# ---------------------------------------------------------------------------

def _generer_unique(colonne: str, fabrique) -> str:
    """Génère une valeur aléatoire absente de la colonne visée."""
    db = get_db()
    for _ in range(50):
        valeur = fabrique()
        existe = db.execute(
            f"SELECT 1 FROM commandes WHERE {colonne} = ?", (valeur,)
        ).fetchone()
        if not existe:
            return valeur
    raise RuntimeError(f"Impossible de générer une valeur unique pour {colonne}")


def generer_reference() -> str:
    """Référence courte à rappeler lors du paiement Wave. Ex. DLW-7K2M"""
    def fabrique():
        return "DLW-" + "".join(secrets.choice(ALPHABET_CODE) for _ in range(4))
    return _generer_unique("reference", fabrique)


def generer_code_acces() -> str:
    """Code d'accès personnel du client. Ex. DTV-4H8Q-P3XZ"""
    def fabrique():
        bloc = lambda: "".join(secrets.choice(ALPHABET_CODE) for _ in range(4))
        return f"DTV-{bloc()}-{bloc()}"
    return _generer_unique("code_acces", fabrique)


def creer_commande(nom: str, telephone: str, montant: int) -> str:
    db = get_db()
    reference = generer_reference()
    db.execute(
        "INSERT INTO commandes (reference, nom, telephone, montant, statut, cree_le) "
        "VALUES (?, ?, ?, ?, 'nouvelle', ?)",
        (reference, nom, telephone, montant, maintenant()),
    )
    db.commit()
    return reference


def commande_par_reference(reference: str):
    return get_db().execute(
        "SELECT * FROM commandes WHERE reference = ?", (reference.upper(),)
    ).fetchone()


def commande_par_code(code: str):
    """Ne retourne la commande que si le code est actif (statut « validee »)."""
    if not code:
        return None
    return get_db().execute(
        "SELECT * FROM commandes WHERE code_acces = ? AND statut = 'validee'",
        (code.upper(),),
    ).fetchone()


def declarer_paiement(reference: str, numero_wave: str):
    """Le client déclare avoir payé : la commande passe en vérification."""
    db = get_db()
    db.execute(
        "UPDATE commandes SET statut = 'a_verifier', numero_wave_client = ?, "
        "paye_declare_le = ? WHERE reference = ? "
        "AND statut IN ('nouvelle', 'a_verifier')",
        (numero_wave, maintenant(), reference.upper()),
    )
    db.commit()


def valider_commande(commande_id: int, admin_email: str) -> str:
    """Valide le paiement et attribue un code d'accès (idempotent)."""
    db = get_db()
    ligne = db.execute(
        "SELECT code_acces FROM commandes WHERE id = ?", (commande_id,)
    ).fetchone()
    if ligne is None:
        raise ValueError("Commande introuvable")

    code = ligne["code_acces"] or generer_code_acces()
    db.execute(
        "UPDATE commandes SET statut = 'validee', code_acces = ?, traite_le = ?, "
        "traite_par = ? WHERE id = ?",
        (code, maintenant(), admin_email, commande_id),
    )
    db.commit()
    return code


def rejeter_commande(commande_id: int, admin_email: str, note: str = ""):
    db = get_db()
    db.execute(
        "UPDATE commandes SET statut = 'rejetee', note = ?, traite_le = ?, "
        "traite_par = ? WHERE id = ?",
        (note, maintenant(), admin_email, commande_id),
    )
    db.commit()


def revoquer_commande(commande_id: int, admin_email: str):
    """Bloque un code déjà distribué (partage abusif) et libère ses appareils."""
    db = get_db()
    db.execute(
        "UPDATE commandes SET statut = 'revoquee', traite_le = ?, traite_par = ? "
        "WHERE id = ?",
        (maintenant(), admin_email, commande_id),
    )
    db.execute("DELETE FROM sessions_acces WHERE commande_id = ?", (commande_id,))
    db.commit()


def liberer_appareils(commande_id: int):
    """Réinitialise les appareils d'un code sans le désactiver.

    Sert quand un client change de téléphone ou vide son navigateur.
    """
    db = get_db()
    db.execute("DELETE FROM sessions_acces WHERE commande_id = ?", (commande_id,))
    db.commit()


def marquer_code_envoye(commande_id: int):
    db = get_db()
    db.execute("UPDATE commandes SET code_envoye = 1 WHERE id = ?", (commande_id,))
    db.commit()


def vider_commandes() -> dict:
    """Efface toutes les commandes, leurs accès et les tentatives.

    Les réglages du direct sont conservés : on repart à zéro côté clients
    sans avoir à ressaisir le lien Wave, le prix ou le message WhatsApp.

    Opération irréversible : les mots de passe déjà distribués cessent
    aussitôt de fonctionner. Renvoie le décompte de ce qui a été supprimé,
    pour pouvoir l'annoncer honnêtement.
    """
    db = get_db()
    compte = {
        "commandes": db.execute(
            "SELECT COUNT(*) AS n FROM commandes").fetchone()["n"],
        "appareils": db.execute(
            "SELECT COUNT(*) AS n FROM sessions_acces").fetchone()["n"],
    }

    # sessions_acces part en cascade, mais SQLite n'applique les clés
    # étrangères que si le PRAGMA est actif : on supprime explicitement.
    db.execute("DELETE FROM sessions_acces")
    db.execute("DELETE FROM commandes")
    db.execute("DELETE FROM tentatives")
    db.commit()
    return compte


def liste_commandes(statut: str = None, limite: int = 200):
    db = get_db()
    if statut and statut != "toutes":
        return db.execute(
            "SELECT * FROM commandes WHERE statut = ? ORDER BY id DESC LIMIT ?",
            (statut, limite),
        ).fetchall()
    return db.execute(
        "SELECT * FROM commandes ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()


def statistiques():
    db = get_db()
    lignes = db.execute(
        "SELECT statut, COUNT(*) AS n, COALESCE(SUM(montant), 0) AS total "
        "FROM commandes GROUP BY statut"
    ).fetchall()
    par_statut = {l["statut"]: {"n": l["n"], "total": l["total"]} for l in lignes}

    # Le chiffre d'affaires inclut les codes révoqués : l'argent a bien été encaissé
    encaisse = sum(
        v["total"] for k, v in par_statut.items() if k in ("validee", "revoquee")
    )
    return {
        "par_statut": par_statut,
        "nb_validees": par_statut.get("validee", {}).get("n", 0),
        "nb_a_verifier": par_statut.get("a_verifier", {}).get("n", 0),
        "nb_nouvelles": par_statut.get("nouvelle", {}).get("n", 0),
        "encaisse": encaisse,
        "spectateurs": db.execute(
            "SELECT COUNT(*) AS n FROM sessions_acces"
        ).fetchone()["n"],
    }


# ---------------------------------------------------------------------------
# Sessions d'accès (limitation du nombre d'appareils par code)
# ---------------------------------------------------------------------------

# Au-delà de ce délai sans activité, un appareil est considéré comme parti
# et libère sa place. Un client qui a payé doit pouvoir revenir depuis un
# autre téléphone, ou après avoir vidé son navigateur : le mot de passe est
# la preuve d'achat, le cookie n'est qu'une commodité.
INACTIVITE_LIBERATRICE = 30 * 60  # 30 minutes


def enregistrer_session(commande_id: int, device_id: str, ip: str,
                        user_agent: str, max_appareils: int) -> bool:
    """Autorise l'appareil s'il est déjà connu, ou si le quota le permet.

    Le quota porte sur les appareils qui regardent *en ce moment*, pas sur
    tous ceux vus depuis l'achat : les sessions inactives depuis plus de
    trente minutes sont oubliées. Le partage simultané reste donc empêché,
    sans jamais enfermer un client qui a changé d'appareil.
    """
    db = get_db()
    connue = db.execute(
        "SELECT id FROM sessions_acces WHERE commande_id = ? AND device_id = ?",
        (commande_id, device_id),
    ).fetchone()

    if connue:
        db.execute(
            "UPDATE sessions_acces SET derniere_vue = ?, ip = ? WHERE id = ?",
            (maintenant(), ip, connue["id"]),
        )
        db.commit()
        return True

    # Les appareils inactifs cèdent leur place avant tout comptage
    db.execute(
        "DELETE FROM sessions_acces WHERE commande_id = ? "
        "AND derniere_vue < datetime('now', 'localtime', ?)",
        (commande_id, f"-{INACTIVITE_LIBERATRICE} seconds"),
    )

    total = db.execute(
        "SELECT COUNT(*) AS n FROM sessions_acces WHERE commande_id = ?",
        (commande_id,),
    ).fetchone()["n"]
    if total >= max_appareils:
        return False

    db.execute(
        "INSERT INTO sessions_acces (commande_id, device_id, ip, user_agent, "
        "cree_le, derniere_vue) VALUES (?, ?, ?, ?, ?, ?)",
        (commande_id, device_id, ip, (user_agent or "")[:250],
         maintenant(), maintenant()),
    )
    db.commit()
    return True


def sessions_de_commande(commande_id: int):
    return get_db().execute(
        "SELECT * FROM sessions_acces WHERE commande_id = ? ORDER BY id",
        (commande_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Limitation des tentatives de code (anti-force brute)
# ---------------------------------------------------------------------------

def enregistrer_tentative(ip: str, appareil: str, code: str):
    db = get_db()
    db.execute(
        "INSERT INTO tentatives (ip, appareil, code, cree_le) VALUES (?, ?, ?, ?)",
        (ip, appareil, (code or "")[:40], maintenant()),
    )
    db.commit()


def tentatives_recentes(ip: str, appareil: str, fenetre_secondes: int) -> tuple:
    """Nombre d'essais ratés récents, par appareil puis par adresse IP.

    Le comptage par appareil est le garde-fou principal : au Sénégal, des
    centaines de clients mobiles partagent la même IP publique derrière le
    NAT de l'opérateur. Bloquer sur l'IP seule priverait d'accès des
    spectateurs qui ont payé, à cause des fautes de frappe de leurs voisins.
    """
    db = get_db()
    borne = f"-{fenetre_secondes} seconds"

    par_appareil = db.execute(
        "SELECT COUNT(*) AS n FROM tentatives WHERE appareil = ? "
        "AND cree_le >= datetime('now', 'localtime', ?)",
        (appareil, borne),
    ).fetchone()["n"]

    par_ip = db.execute(
        "SELECT COUNT(*) AS n FROM tentatives WHERE ip = ? "
        "AND cree_le >= datetime('now', 'localtime', ?)",
        (ip, borne),
    ).fetchone()["n"]

    return par_appareil, par_ip


def purger_tentatives(appareil: str):
    """Remet le compteur à zéro après une saisie réussie."""
    db = get_db()
    db.execute("DELETE FROM tentatives WHERE appareil = ?", (appareil,))
    db.commit()
