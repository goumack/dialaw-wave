"""Dialaw TV Live — vente d'accès à un direct YouTube payable par Wave.

Parcours client :
    1. Page publique (le lien placé dans la description de la chaîne YouTube)
    2. Formulaire : numéro WhatsApp        → une référence de commande
    3. Paiement sur le lien Wave Business, référence rappelée en motif
    4. Le client clique « J'ai payé »     → commande à vérifier
    5. L'administrateur valide en 1 clic  → un mot de passe est généré
    6. Il part par WhatsApp et s'affiche sur la page de suivi
    7. Le client le saisit                → le direct s'ouvre

Lancement : python app.py
"""

import os
import secrets
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, abort, jsonify,
)
from werkzeug.security import check_password_hash

import apercu as ap
import connexion as cx
import database as bd
import diffusion as dif
import utils as u
from config import CONFIG_PAR_DEFAUT, Config

app = Flask(__name__)
app.config.from_object(Config)
app.teardown_appcontext(bd.close_db)

COOKIE_APPAREIL = "dtv_appareil"

# Libellés affichés à la place des identifiants techniques de statut
LIBELLES_STATUT = {
    "nouvelle": "En attente de paiement",
    "a_verifier": "Paiement à vérifier",
    "validee": "Validée",
    "rejetee": "Rejetée",
    "revoquee": "Mot de passe révoqué",
}


# ---------------------------------------------------------------------------
# Filtres et variables de gabarit
# ---------------------------------------------------------------------------

app.jinja_env.filters["montant"] = u.formater_montant
app.jinja_env.filters["tel"] = u.telephone_affichage
app.jinja_env.filters["date_fr"] = u.date_affichage
app.jinja_env.filters["statut"] = lambda s: LIBELLES_STATUT.get(s, s)


@app.context_processor
def injecter_config():
    """Rend la configuration du direct disponible dans tous les gabarits.

    Ce processeur s'exécute avant chaque rendu : s'il laissait passer une
    erreur de base, toute page du site renverrait un 500 nu — y compris la
    page d'erreur, qui a elle aussi besoin de ces valeurs. On retombe donc
    sur les valeurs par défaut, quitte à afficher une page dégradée.
    """
    try:
        configuration = bd.lire_config()
    except Exception as erreur:  # noqa: BLE001 — la page doit rester affichable
        app.logger.error("Configuration illisible — %s", erreur)
        configuration = dict(CONFIG_PAR_DEFAUT)

    return {
        "cfg": configuration,
        "devise": app.config["DEVISE"],
        "admin_connecte": session.get("admin_email"),
        # Adresse absolue obligatoire : WhatsApp va chercher l'image depuis
        # ses propres serveurs, un chemin relatif n'y mènerait nulle part.
        "url_apercu": url_du_site(configuration) + "/apercu.png",
    }


# ---------------------------------------------------------------------------
# Aides
# ---------------------------------------------------------------------------

def ip_client() -> str:
    """Adresse IP réelle du visiteur, même derrière un proxy (Render, Nginx)."""
    entete = request.headers.get("X-Forwarded-For", "")
    if entete:
        return entete.split(",")[0].strip()
    return request.remote_addr or "inconnue"


def identifiant_appareil() -> str:
    """Identifiant persistant de l'appareil, conservé dans un cookie."""
    return request.cookies.get(COOKIE_APPAREIL) or secrets.token_urlsafe(16)


def poser_cookie_appareil(reponse, appareil: str):
    """Fixe le cookie d'appareil sur la réponse (6 mois)."""
    reponse.set_cookie(
        COOKIE_APPAREIL, appareil,
        max_age=60 * 60 * 24 * 180, httponly=True, samesite="Lax",
        secure=app.config["SESSION_COOKIE_SECURE"],
    )
    return reponse


def url_du_site(config: dict) -> str:
    """URL publique du site, utilisée dans les messages WhatsApp."""
    return (config.get("site_url") or request.url_root).rstrip("/")


def entier(valeur, defaut: int) -> int:
    """Conversion tolérante : la configuration est saisie à la main."""
    try:
        return int(str(valeur).strip())
    except (TypeError, ValueError):
        return defaut


def admin_requis(vue):
    """Protège les routes du back-office."""
    @wraps(vue)
    def enveloppe(*args, **kwargs):
        if not session.get("admin_email"):
            flash("Merci de vous connecter pour accéder au back-office.", "info")
            return redirect(url_for("admin_connexion", suite=request.path))
        return vue(*args, **kwargs)
    return enveloppe


def message_pour(commande, config) -> str:
    """Construit le message WhatsApp de livraison du mot de passe."""
    return u.construire_message(
        config.get("message_whatsapp", ""),
        nom=commande["nom"],
        montant=u.formater_montant(commande["montant"]),
        devise=app.config["DEVISE"],
        titre=config.get("titre_live", ""),
        code=commande["code_acces"] or "",
        reference=commande["reference"],
        # {lien} ouvre le direct d'un seul geste, le mot de passe étant porté
        # par l'URL. {lien_simple} reste disponible pour une saisie manuelle.
        # La forme courte est construite à la main : url_for(), appelé hors
        # de cette route, produirait « ?code_du_lien=… » — fonctionnel mais
        # inélégant dans un message envoyé à un client.
        lien=(f"{url_du_site(config)}/acces/{commande['code_acces']}"
              if commande["code_acces"]
              else url_du_site(config) + url_for("acces")),
        lien_simple=url_du_site(config) + url_for("acces"),
    )


# ---------------------------------------------------------------------------
# Parcours client
# ---------------------------------------------------------------------------

@app.route("/")
def accueil():
    # La configuration est déjà chargée par le context_processor, qui sait
    # retomber sur les valeurs par défaut si la base est momentanément
    # injoignable : la vitrine reste ainsi affichable en toute circonstance.
    config = injecter_config()["cfg"]
    return render_template(
        "index.html",
        ventes_ouvertes=config.get("ventes_ouvertes") == "1",
        termine=u.live_termine(config),
    )


@app.route("/commander", methods=["GET", "POST"])
def commander():
    config = bd.lire_config()

    if config.get("ventes_ouvertes") != "1":
        flash("Les ventes sont actuellement fermées.", "erreur")
        return redirect(url_for("accueil"))

    if request.method == "POST":
        nom = " ".join((request.form.get("nom") or "").split())
        saisie_tel = request.form.get("telephone", "")
        telephone = u.normaliser_telephone(saisie_tel)

        # Seul le numéro WhatsApp est indispensable : c'est par lui que le
        # mot de passe sera livré. Exiger le nom ferait abandonner des clients.
        if not telephone:
            flash("Numéro WhatsApp invalide. Exemple attendu : 77 123 45 67.",
                  "erreur")
            return render_template("commander.html", nom=nom, telephone=saisie_tel)

        if not nom:
            nom = "Client " + telephone[-4:]

        reference = bd.creer_commande(nom, telephone, entier(config.get("prix"), 0))
        return redirect(url_for("paiement", reference=reference))

    return render_template("commander.html", nom="", telephone="")


@app.route("/paiement/<reference>", methods=["GET", "POST"])
def paiement(reference):
    commande = bd.commande_par_reference(reference)
    if commande is None:
        abort(404)

    config = bd.lire_config()

    if request.method == "POST":
        numero = u.normaliser_telephone(request.form.get("numero_wave"))
        if not numero:
            flash("Indiquez le numéro Wave utilisé pour le paiement.", "erreur")
            return render_template(
                "paiement.html", commande=commande,
                lien_wave=config.get("lien_wave", ""),
                navigateur_integre=u.est_navigateur_integre(
                    request.headers.get("User-Agent", "")
                ),
            )

        bd.declarer_paiement(commande["reference"], numero)
        flash(
            "Merci ! Votre paiement est en cours de vérification. "
            "Vous recevrez votre mot de passe par WhatsApp dans quelques minutes.",
            "succes",
        )
        return redirect(url_for("suivi", reference=commande["reference"]))

    if commande["statut"] not in ("nouvelle", "a_verifier"):
        return redirect(url_for("suivi", reference=commande["reference"]))

    return render_template(
        "paiement.html",
        commande=commande,
        lien_wave=config.get("lien_wave", ""),
        # Ouverte depuis WhatsApp, la page tourne dans un mini-navigateur
        # incapable de lancer l'application Wave : le lien y échoue et
        # renvoie vers le Play Store. Le client doit le savoir avant de cliquer.
        navigateur_integre=u.est_navigateur_integre(
            request.headers.get("User-Agent", "")
        ),
    )


@app.route("/suivi/<reference>")
def suivi(reference):
    commande = bd.commande_par_reference(reference)
    if commande is None:
        abort(404)

    config = bd.lire_config()
    numero_support = config.get("whatsapp_support", "")
    lien_support = u.lien_whatsapp(
        numero_support,
        f"Bonjour Dialaw TV, je suis {commande['nom']}. "
        f"Ma commande {commande['reference']} est en attente de validation.",
    ) if numero_support else ""

    return render_template(
        "suivi.html",
        commande=commande,
        lien_support=lien_support,
        # La page se rafraîchit seule tant que la commande n'est pas tranchée
        auto_refresh=commande["statut"] in ("nouvelle", "a_verifier"),
    )


@app.route("/acces", methods=["GET", "POST"])
@app.route("/acces/<code_du_lien>", methods=["GET"])
def acces(code_du_lien=None):
    config = bd.lire_config()
    # L'appareil est identifié dès l'affichage du formulaire : c'est lui qui
    # sert de compteur anti-force brute, pas seulement l'adresse IP.
    appareil = identifiant_appareil()

    def rendre(code_saisi=""):
        # En cas d'échec d'un lien direct, le mot de passe reste affiché dans
        # le champ : le client n'a pas à le retrouver dans sa conversation.
        return poser_cookie_appareil(
            app.make_response(
                render_template("acces.html", code_saisi=code_saisi)
            ),
            appareil,
        )

    # Lien direct reçu par WhatsApp : /acces/DTV-XXXX-XXXX, ou /acces?c=…
    # Le mot de passe passe alors par l'URL et subit exactement les mêmes
    # contrôles qu'une saisie au clavier — quota d'appareils compris.
    code_url = code_du_lien or request.args.get("c", "")

    if request.method != "POST" and not code_url:
        return rendre()

    ip = ip_client()
    if request.method == "POST":
        code = (request.form.get("code") or "")
    else:
        code = code_url
    code = code.strip().upper().replace(" ", "")

    # Le direct terminé est annoncé avant tout : le message est le même pour
    # un code valide comme pour une faute de frappe, inutile de pénaliser.
    if u.live_termine(config):
        flash("Ce direct est terminé. Merci d'avoir suivi Dialaw TV !", "info")
        return rendre(code)

    essais_appareil, essais_ip = bd.tentatives_recentes(
        ip, appareil, app.config["FENETRE_TENTATIVES"]
    )
    if essais_appareil >= app.config["MAX_TENTATIVES_CODE"] or \
            essais_ip >= app.config["MAX_TENTATIVES_IP"]:
        flash(
            "Trop de tentatives. Patientez 15 minutes ou contactez le support.",
            "erreur",
        )
        return rendre(code)

    commande = bd.commande_par_code(code)
    if commande is None:
        bd.enregistrer_tentative(ip, appareil, code)
        flash(
            "Mot de passe invalide ou désactivé. Vérifiez celui reçu par WhatsApp.",
            "erreur",
        )
        return rendre(code)

    max_appareils = max(1, entier(config.get("max_appareils"), 1))
    if not bd.enregistrer_session(commande["id"], appareil, ip,
                                  request.headers.get("User-Agent", ""),
                                  max_appareils):
        flash(
            f"Ce mot de passe est en cours d'utilisation sur "
            f"{max_appareils} appareil(s). Fermez le direct sur l'autre "
            "appareil, ou réessayez dans une demi-heure : la place se libère "
            "toute seule.",
            "erreur",
        )
        return rendre(code)

    bd.purger_tentatives(appareil)
    session["commande_id"] = commande["id"]
    session["code"] = commande["code_acces"]
    session.permanent = True

    return poser_cookie_appareil(redirect(url_for("live")), appareil)


@app.route("/live")
def live():
    """Lecteur protégé. L'identifiant YouTube n'est servi que par cette page."""
    commande_id = session.get("commande_id")
    if not commande_id:
        flash("Saisissez votre mot de passe pour regarder le direct.", "info")
        return redirect(url_for("acces"))

    # Relecture en base à chaque affichage : une révocation coupe l'accès aussitôt
    commande = bd.commande_par_code(session.get("code", ""))
    if commande is None or commande["id"] != commande_id:
        session.clear()
        flash("Votre accès n'est plus valide. Contactez le support.", "erreur")
        return redirect(url_for("acces"))

    config = bd.lire_config()
    if u.live_termine(config):
        session.clear()
        flash("Ce direct est terminé. Merci d'avoir suivi Dialaw TV !", "info")
        return redirect(url_for("acces"))

    # Deux modes de diffusion selon ce qui est configuré : une adresse de
    # flux HLS est relayée par le site (aucun logo, aucun lien sortant),
    # sinon on retombe sur l'intégration YouTube.
    source = config.get("youtube_id", "")
    if dif.est_flux_direct(source):
        bd.enregistrer_session(
            commande["id"], identifiant_appareil(), ip_client(),
            request.headers.get("User-Agent", ""), 10_000,
        )
        # Relais ou lecture directe : au-delà de quelques dizaines de
        # spectateurs, le relais épuiserait la bande passante de
        # l'hébergement en quelques minutes. Le serveur de diffusion,
        # lui, est dimensionné pour ça.
        if config.get("relayer_flux") == "1":
            adresse = url_for("flux", ressource=dif.chemin_relatif(source))
        else:
            adresse = source

        return render_template(
            "live.html",
            commande=commande,
            flux_direct=adresse,
            youtube_id="",
            filigrane=f"{commande['nom']} · {u.telephone_masque(commande['telephone'])}",
            domaine=request.host.split(":")[0],
        )

    youtube_id = u.extraire_youtube_id(source)
    if not youtube_id:
        return render_template("live.html", commande=commande, youtube_id="",
                               flux_direct="", filigrane="", domaine="")

    # Le quota est ignoré ici : l'appareil est déjà autorisé, on ne fait
    # qu'actualiser sa dernière vue pour le comptage des spectateurs.
    bd.enregistrer_session(
        commande["id"], identifiant_appareil(), ip_client(),
        request.headers.get("User-Agent", ""), 10_000,
    )

    return render_template(
        "live.html",
        commande=commande,
        youtube_id=youtube_id,
        flux_direct="",
        filigrane=f"{commande['nom']} · {u.telephone_masque(commande['telephone'])}",
        # Le chat YouTube exige le domaine hôte exact pour accepter l'intégration
        domaine=request.host.split(":")[0],
    )


@app.route("/apercu.png")
def apercu_png():
    """Image affichée par WhatsApp quand un lien du site est partagé.

    Volontairement publique : WhatsApp la récupère depuis ses propres
    serveurs, qui n'ont aucune session. Elle ne révèle donc rien de sensible
    — ni identifiant YouTube, ni mot de passe, seulement le titre et le prix.
    """
    config = bd.lire_config()
    try:
        image = ap.construire(
            titre=config.get("titre_live", "Direct Dialaw TV"),
            prix=u.formater_montant(config.get("prix", 0)),
            devise=app.config["DEVISE"],
        )
    except Exception as erreur:  # noqa: BLE001 — un aperçu ne doit rien casser
        app.logger.error("Aperçu impossible à générer — %s", erreur)
        abort(404)

    reponse = app.make_response(image)
    reponse.headers["Content-Type"] = "image/png"
    # WhatsApp met l'aperçu en cache : une heure suffit pour qu'un changement
    # de titre ou de prix soit repris avant l'émission suivante.
    reponse.headers["Cache-Control"] = "public, max-age=3600"
    return reponse


@app.route("/reveil")
def reveil():
    """Point d'appel des services de surveillance (UptimeRobot, cron-job.org).

    L'hébergement gratuit endort le service après 15 minutes sans visite, et
    le réveil coûte alors une cinquantaine de secondes au premier client. Une
    requête toutes les 10 à 14 minutes maintient l'application debout.

    La base est interrogée au passage : le service peut répondre alors que
    PostgreSQL est injoignable, et cette page doit le signaler plutôt que de
    rassurer à tort.
    """
    # get_db() peut échouer dès l'ouverture de la connexion : le try doit
    # donc l'englober, sinon la surveillance reçoit une erreur 500 muette
    # au lieu du diagnostic.
    try:
        bd.get_db().execute("SELECT 1")
        base = "ok"
        code = 200
    except Exception as erreur:  # noqa: BLE001 — on renvoie l'état, sans planter
        app.logger.error("Réveil : base injoignable — %s", erreur)
        base = "injoignable"
        code = 503

    reponse = jsonify({
        "service": "dialawtv-live",
        "etat": "actif",
        "base": base,
        "moteur": cx.moteur(),
        "horodatage": bd.maintenant(),
    })
    # Sans cet en-tête, un cache intermédiaire pourrait répondre à la place
    # du serveur — le service resterait alors endormi malgré les pings.
    reponse.headers["Cache-Control"] = "no-store"
    return reponse, code


def spectateur_autorise():
    """Commande du spectateur connecté, ou None si l'accès n'est plus valide.

    Relue en base à chaque appel : une révocation coupe le flux en cours.
    """
    if not session.get("commande_id"):
        return None
    commande = bd.commande_par_code(session.get("code", ""))
    if commande is None or commande["id"] != session["commande_id"]:
        return None
    if u.live_termine(bd.lire_config()):
        return None
    return commande


@app.route("/flux/<path:ressource>")
def flux(ressource):
    """Relaie le flux vidéo, réservé aux spectateurs ayant payé.

    Chaque segment repasse par ce contrôle : couper un accès interrompt la
    lecture en cours, sans attendre que le spectateur recharge la page.
    """
    if spectateur_autorise() is None:
        abort(403)

    url_flux = bd.lire_config().get("youtube_id", "")
    if not dif.est_flux_direct(url_flux):
        abort(404)

    if not dif.chemin_autorise(ressource):
        abort(403)

    resultat = dif.recuperer(dif.url_absolue(url_flux, ressource))
    if resultat is None:
        # Le serveur de diffusion ne répond pas : c'est lui, pas nous
        abort(502)

    contenu, _ = resultat
    if ressource.lower().endswith(".m3u8"):
        contenu = dif.reecrire_playlist(contenu, "/flux/")

    reponse = app.make_response(contenu)
    reponse.headers["Content-Type"] = dif.type_mime(ressource)
    # Un direct ne se met pas en cache : le spectateur doit voir l'instant
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


@app.route("/quitter")
def quitter():
    session.pop("commande_id", None)
    session.pop("code", None)
    flash("Vous êtes déconnecté du direct.", "info")
    return redirect(url_for("acces"))


# ---------------------------------------------------------------------------
# Back-office
# ---------------------------------------------------------------------------

@app.route("/admin/connexion", methods=["GET", "POST"])
def admin_connexion():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        mot_de_passe = request.form.get("mot_de_passe") or ""

        ligne = bd.get_db().execute(
            "SELECT * FROM admins WHERE email = ?", (email,)
        ).fetchone()

        if ligne and check_password_hash(ligne["mot_de_passe_hash"], mot_de_passe):
            session["admin_email"] = ligne["email"]
            session.permanent = True
            suite = request.args.get("suite")
            # On ne suit que les chemins internes, jamais une URL externe
            return redirect(suite if suite and suite.startswith("/admin")
                            else url_for("admin_tableau"))

        flash("Identifiants incorrects.", "erreur")

    return render_template("admin_connexion.html")


@app.route("/admin/deconnexion")
def admin_deconnexion():
    session.pop("admin_email", None)
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("admin_connexion"))


@app.route("/admin")
@admin_requis
def admin_tableau():
    statut = request.args.get("statut", "a_verifier")
    config = bd.lire_config()

    # Un lien WhatsApp prêt à l'emploi est calculé pour chaque code déjà généré
    lignes = [
        {
            "c": commande,
            "wa": u.lien_whatsapp(commande["telephone"],
                                  message_pour(commande, config))
                  if commande["code_acces"] else "",
        }
        for commande in bd.liste_commandes(statut)
    ]

    return render_template("admin.html", lignes=lignes, statut=statut,
                           stats=bd.statistiques())


@app.route("/admin/commande/<int:commande_id>/<action>", methods=["POST"])
@admin_requis
def admin_action(commande_id, action):
    admin = session["admin_email"]
    statut_retour = request.form.get("statut", "a_verifier")

    if action == "valider":
        code = bd.valider_commande(commande_id, admin)
        flash(f"Paiement validé. Mot de passe généré : {code} — "
              "cliquez sur « Envoyer sur WhatsApp ».", "succes")

    elif action == "whatsapp":
        # Marque la commande comme envoyée, puis ouvre WhatsApp avec le
        # message déjà rédigé (le formulaire vise un nouvel onglet).
        commande = bd.get_db().execute(
            "SELECT * FROM commandes WHERE id = ?", (commande_id,)
        ).fetchone()
        if commande is None or not commande["code_acces"]:
            abort(404)
        bd.marquer_code_envoye(commande_id)
        return redirect(
            u.lien_whatsapp(commande["telephone"],
                            message_pour(commande, bd.lire_config()))
        )

    elif action == "rejeter":
        bd.rejeter_commande(commande_id, admin,
                            request.form.get("note", "Paiement non retrouvé"))
        flash("Commande rejetée.", "info")

    elif action == "revoquer":
        bd.revoquer_commande(commande_id, admin)
        flash("Mot de passe révoqué : l'accès est coupé immédiatement.", "info")

    elif action == "liberer":
        bd.liberer_appareils(commande_id)
        flash("Appareils réinitialisés : le client peut se reconnecter.", "succes")

    elif action == "envoye":
        bd.marquer_code_envoye(commande_id)
        flash("Commande marquée comme envoyée.", "succes")

    else:
        abort(404)

    return redirect(url_for("admin_tableau", statut=statut_retour))


@app.route("/admin/config", methods=["GET", "POST"])
@admin_requis
def admin_config():
    if request.method == "POST":
        champs = (
            "titre_live", "description_live", "prix", "lien_wave", "numero_wave",
            "youtube_id", "live_debut", "live_fin", "max_appareils",
            "whatsapp_support", "message_whatsapp", "site_url",
        )
        valeurs = {c: (request.form.get(c) or "").strip() for c in champs}

        # Cases à cocher : absentes du formulaire lorsqu'elles sont décochées
        valeurs["ventes_ouvertes"] = "1" if request.form.get("ventes_ouvertes") else "0"
        valeurs["afficher_chat"] = "1" if request.form.get("afficher_chat") else "0"
        valeurs["relayer_flux"] = "1" if request.form.get("relayer_flux") else "0"

        # Garde-fou : une URL d'ingestion RTMP collée ici serait publiée à
        # chaque spectateur, qui pourrait alors diffuser sur la chaîne.
        if u.ressemble_a_rtmp(valeurs["youtube_id"]):
            flash(
                "⚠️ Vous avez collé une adresse RTMP (celle d'OBS). Ne la "
                "diffusez jamais : elle permet d'émettre sur votre chaîne. "
                "Collez ici le lien de visionnage du direct, de la forme "
                "https://youtu.be/…",
                "erreur",
            )
            return redirect(url_for("admin_config"))

        # Une adresse de flux HLS est conservée telle quelle : c'est le mode
        # de diffusion sans YouTube, relayé par le site.
        if valeurs["youtube_id"] and not dif.est_flux_direct(valeurs["youtube_id"]):
            identifiant = u.extraire_youtube_id(valeurs["youtube_id"])
            if not identifiant:
                flash(
                    "Source non reconnue. Collez soit l'URL de votre direct "
                    "YouTube, soit l'adresse de votre flux se terminant "
                    "par .m3u8",
                    "erreur",
                )
                return redirect(url_for("admin_config"))
            valeurs["youtube_id"] = identifiant

        # Le numéro Wave était enregistré tel que saisi : le filtre d'affichage
        # ne le reconnaissait pas et il ressortait mal formaté sur la page de
        # paiement, là où le client en a le plus besoin.
        valeurs["numero_wave"] = u.normaliser_telephone(valeurs["numero_wave"])

        valeurs["whatsapp_support"] = u.normaliser_telephone(
            valeurs["whatsapp_support"]
        )
        valeurs["prix"] = str(max(0, entier(valeurs["prix"], 0)))
        valeurs["max_appareils"] = str(max(1, entier(valeurs["max_appareils"], 1)))

        bd.ecrire_config(valeurs)
        flash("Configuration enregistrée.", "succes")
        return redirect(url_for("admin_config"))

    return render_template("admin_config.html")


MOT_DE_CONFIRMATION = "EFFACER"


@app.route("/admin/reinitialiser", methods=["POST"])
@admin_requis
def admin_reinitialiser():
    """Efface toutes les commandes après confirmation écrite.

    Un mot à recopier plutôt qu'un simple clic : cette action coupe l'accès
    de clients qui ont payé, elle ne doit pas pouvoir partir d'un geste
    machinal sur un téléphone, en pleine émission.
    """
    saisie = (request.form.get("confirmation") or "").strip().upper()
    if saisie != MOT_DE_CONFIRMATION:
        flash(
            f"Réinitialisation annulée : il faut écrire « {MOT_DE_CONFIRMATION} » "
            "pour confirmer.",
            "erreur",
        )
        return redirect(url_for("admin_config"))

    compte = bd.vider_commandes()
    app.logger.warning(
        "Réinitialisation par %s : %s commandes, %s appareils supprimés",
        session["admin_email"], compte["commandes"], compte["appareils"],
    )
    flash(
        f"Réinitialisation effectuée : {compte['commandes']} commande(s) et "
        f"{compte['appareils']} appareil(s) supprimés. "
        "Vos réglages sont conservés.",
        "succes",
    )
    return redirect(url_for("admin_tableau"))


@app.route("/admin/commande/<int:commande_id>/appareils")
@admin_requis
def admin_appareils(commande_id):
    """Appareils rattachés à un code : utile pour repérer les partages."""
    return jsonify([dict(s) for s in bd.sessions_de_commande(commande_id)])


# ---------------------------------------------------------------------------
# Erreurs
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def page_introuvable(_):
    return render_template("erreur.html", code=404,
                           message="Cette page n'existe pas."), 404


@app.errorhandler(500)
def erreur_serveur(_):
    return render_template("erreur.html", code=500,
                           message="Une erreur est survenue. Veuillez réessayer."), 500


def verifier_securite_production():
    """Bloque le démarrage en ligne avec des secrets d'usine.

    Une mise en ligne avec le mot de passe par défaut laisserait le
    back-office — et donc les mots de passe de tous les clients — ouvert
    à quiconque a lu le dépôt GitHub.
    """
    if os.environ.get("FLASK_ENV") != "production":
        return

    manquants = []
    if app.config["ADMIN_MOT_DE_PASSE"] == app.config["MOT_DE_PASSE_USINE"]:
        manquants.append("ADMIN_MOT_DE_PASSE")
    if not os.environ.get("SECRET_KEY"):
        manquants.append("SECRET_KEY")

    if manquants:
        raise RuntimeError(
            "Démarrage refusé : en production, ces variables d'environnement "
            "doivent être définies avec des valeurs personnelles — "
            + ", ".join(manquants)
        )

    # Sans base distante, l'hébergeur repart d'un disque vierge à chaque
    # déploiement : les ventes et les mots de passe déjà livrés seraient
    # perdus sans que rien ne le signale. Mieux vaut refuser de démarrer.
    if cx.moteur() != cx.POSTGRES:
        raise RuntimeError(
            "Démarrage refusé : DATABASE_URL n'est pas définie. En ligne, la "
            "base doit être un PostgreSQL distant (Neon) — sinon toutes les "
            "données disparaissent au prochain déploiement."
        )


verifier_securite_production()
bd.init_db(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    print("\n  Dialaw TV Live")
    print(f"  Site public  : http://127.0.0.1:{port}/")
    print(f"  Back-office  : http://127.0.0.1:{port}/admin")
    print(f"  Connexion    : {app.config['ADMIN_EMAIL']} / "
          f"{app.config['ADMIN_MOT_DE_PASSE']}\n")

    app.run(host="0.0.0.0", port=port,
            debug=os.environ.get("FLASK_ENV") != "production")
