# Dialaw TV Live — vendre l'accès à vos directs YouTube avec Wave

Site de billetterie pour vos émissions en direct : le spectateur paie avec
**Wave**, vous validez en un clic, il reçoit son **mot de passe personnel**
sur **WhatsApp** et regarde le direct sur votre propre site.

Écrit en **Python (Flask) + HTML + CSS**. Aucune base de données à installer,
aucun framework JavaScript : SQLite est inclus dans Python.

---

## 1. Démarrage en 2 minutes

Double-cliquez sur **`demarrer.bat`**, ou en ligne de commande :

```bash
pip install -r requirements.txt
python app.py
```

| Adresse | Rôle |
|---|---|
| http://127.0.0.1:5000/ | Le site vu par vos clients |
| http://127.0.0.1:5000/admin | Votre back-office |

Identifiants par défaut : `admin@dialawtv.sn` / `dialaw2026`
(modifiables dans le fichier `.env` — voir §5).

---

## 2. Le parcours, côté client

1. Il ouvre votre lien (celui placé dans la description de votre chaîne YouTube).
2. Il saisit son **numéro WhatsApp** (seul champ obligatoire) → une
   référence type `DLW-7K2M` lui est attribuée.
3. Il appuie sur **« Payer avec Wave »** → votre lien Wave Business s'ouvre.
4. Il revient et clique **« J'ai payé »** en indiquant son numéro Wave.
5. Sa page de suivi se rafraîchit toute seule en attendant votre validation.
6. Dès que vous validez, son **mot de passe** s'affiche et part sur son
   WhatsApp.
7. Il le saisit sur `/acces` → **le direct démarre**.

---

## 3. Le parcours, côté vous (un soir de direct)

Gardez `/admin` ouvert sur votre téléphone — l'écran « À vérifier »
s'actualise tout seul toutes les 20 secondes.

1. Une commande apparaît avec le nom, le montant et **le numéro Wave qui a payé**.
2. Vous vérifiez dans votre application Wave Business que l'argent est bien arrivé.
3. **✓ Valider le paiement** → le mot de passe est généré automatiquement.
4. **➤ Envoyer sur WhatsApp** → WhatsApp s'ouvre avec le message *déjà écrit*
   (lien de visionnage + mot de passe). Vous n'avez qu'à appuyer sur Envoyer.

Total : environ 5 secondes par client.

Si un paiement est introuvable : **✕ Rejeter**. Le client voit le refus sur
sa page de suivi et peut vous contacter.

---

## 4. Réglages du direct (`/admin/config`)

### Le lien de paiement Wave

Vos coordonnées sont **déjà pré-remplies** :

| Réglage | Valeur en place |
|---|---|
| Lien de paiement Wave | `https://pay.wave.com/m/M_sn_wF5yaWQxUVkW/c/sn/` |
| Numéro Wave / WhatsApp | 77 219 77 73 |
| Prix | 1 000 FCFA |

Pour les changer : Wave Business → *Demander un paiement* → copiez le nouveau
lien dans **Lien de paiement Wave Business**.

> **Vérifiez une fois que votre lien impose bien le montant.** S'il laisse le
> montant libre, un client peut envoyer 100 F au lieu de 1 000 et il faudra le
> refuser en pleine soirée.

### Le direct YouTube

**Réglez impérativement votre direct sur « Non répertorié »**, jamais sur
« Public ». Sinon n'importe qui le trouve gratuitement depuis YouTube et
votre billetterie ne sert plus à rien.

Dans YouTube Studio → *Créer* → *Passer en direct* → Visibilité :
**Non répertorié**. Copiez ensuite l'URL du direct et collez-la telle quelle
dans le champ prévu : l'identifiant est extrait automatiquement.

> ### ⛔ Ne confondez jamais ces deux liens
>
> | Lien | À quoi il sert | Qui peut l'avoir |
> |---|---|---|
> | `https://youtu.be/…` | **Regarder** le direct | Vos clients, après paiement |
> | `rtmp://a.rtmp.youtube.com/live2` + clé de flux | **Diffuser** sur votre chaîne depuis OBS | **Vous seul, jamais personne d'autre** |
>
> Le RTMP est l'adresse d'ingestion : quiconque la possède peut émettre sur
> votre antenne à votre place. L'application refuse d'ailleurs de l'enregistrer
> si vous la collez par erreur dans les réglages.

### L'heure de fin

Le champ **Fin d'accès** est votre coupe-circuit : passée cette heure, tous
les mots de passe cessent de fonctionner. Réglez-le à la fin prévue de l'émission.

### Le nombre d'appareils

`1` par défaut : un accès acheté = un seul téléphone. Si un client change de
téléphone ou vide son navigateur, utilisez **« Libérer les appareils »** sur
sa commande, il pourra se reconnecter.

---

## 5. Le fichier `.env`

Copiez `.env.example` en `.env` et changez au minimum ces deux valeurs :

```ini
SECRET_KEY=une-longue-chaine-aleatoire
ADMIN_MOT_DE_PASSE=votre-vrai-mot-de-passe
```

Pour générer une clé solide :

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> Le fichier `.env` et la base `dialaw_live.db` sont déjà exclus de Git.
> Ne les publiez jamais : ils contiennent vos accès et vos ventes.

---

## 6. Le site en ligne

**Adresse publique : https://dialawtv-live.onrender.com**

Deux services, tous deux gratuits :

| Rôle | Service | Ce qu'il contient |
|---|---|---|
| Site web | Render (plan gratuit) | Le code, reconstruit à chaque `git push` |
| Base de données | Neon (PostgreSQL, gratuit) | Réglages, commandes, mots de passe |

**Pourquoi deux services séparés.** Render efface tout son disque à chaque
redéploiement. Tant que la base vivait sur ce disque, chaque mise à jour du
code remettait les réglages et les ventes à zéro. En plaçant la base chez
Neon, elle vit à part et **survit à tous les déploiements**.

La bascule se fait par la seule variable `DATABASE_URL` :

- **absente** → SQLite local, dans un fichier (votre PC) ;
- **présente** → PostgreSQL distant (en ligne).

En production, l'application **refuse de démarrer** si `DATABASE_URL` est
absente : mieux vaut une erreur visible qu'un site qui tourne en perdant
silencieusement les ventes du soir.

### Les variables à définir dans Render

| Variable | Valeur |
|---|---|
| `DATABASE_URL` | La chaîne `postgresql://...` fournie par Neon |
| `ADMIN_EMAIL` | Votre adresse de connexion au back-office |
| `ADMIN_MOT_DE_PASSE` | Votre mot de passe |
| `SECRET_KEY` | Générée automatiquement par Render |
| `FLASK_ENV` | `production` |

### Redéployer après une modification

```bash
git add -A
git commit -m "Description de la modification"
git push
```

Render reconstruit en 3 à 5 minutes. **Vos données ne bougent pas.**

### Ce qui reste à surveiller sur le plan gratuit

Le service s'endort après 15 minutes sans visite : le premier visiteur
attend une cinquantaine de secondes. Ouvrez le site vous-même 5 minutes
avant l'émission pour le réveiller.

### Historique : mettre en ligne ailleurs

Pour héberger sur un autre service :

**Render.com** → *New Web Service* → connectez votre dépôt Git, puis :

| Réglage | Valeur |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app` |
| Variables d'env. | `SECRET_KEY`, `ADMIN_MOT_DE_PASSE`, `FLASK_ENV=production` |

⚠️ Sur les offres gratuites, le disque est effacé à chaque redéploiement —
donc vos commandes aussi. Pour un usage réel, prenez un **disque persistant**
(Render : *Disks*, monté sur le dossier de l'application) ou un petit VPS.

Une fois en ligne, reportez l'adresse obtenue dans **Réglages → Adresse
publique du site** : elle sert à construire le lien envoyé sur WhatsApp.

### Sous Windows, en production locale

```bash
waitress-serve --port=5000 app:app
```

---

## 7. Le lien à mettre sur YouTube

C'est le cœur de la monétisation. Placez l'adresse publique de votre site :

- dans la **description de la chaîne** (onglet *À propos*) ;
- dans la **description de chaque vidéo**, en première ligne ;
- dans les **liens de la bannière** de la chaîne ;
- en **commentaire épinglé** et à l'écran pendant vos directs gratuits.

Exemple de formulation :

> 🔴 Suivez le match en direct et en exclusivité : https://live.dialawtv.sn
> Accès 1 000 FCFA, paiement Wave, mot de passe envoyé immédiatement sur WhatsApp.

---

## 8. Ce que la protection fait — et ne fait pas

Le système décourage sérieusement le partage :

- mot de passe **nominatif**, lié au numéro WhatsApp du client ;
- limité à **1 appareil** ;
- **filigrane** discret sur le lecteur, avec le nom du spectateur ;
- **révocation immédiate** d'un mot de passe depuis le back-office ;
- expiration automatique à la fin du direct.

Ce qu'il faut savoir malgré tout : le lecteur reste une intégration YouTube.
Un spectateur techniquement averti peut lire l'identifiant de la vidéo dans
le code source de la page et transmettre le lien YouTube brut. Les parades
pratiques :

1. **Un direct neuf à chaque émission** — un lien fuité ne vaut que pour un soir.
2. **Surveillez** l'écran « Validées » : un accès utilisé de façon anormale
   se révoque en un clic.
3. Pour une étanchéité totale, il faudrait quitter YouTube pour un service de
   diffusion à jetons signés (Cloudflare Stream, Mux) — beaucoup plus cher,
   à envisager seulement si le volume le justifie.

---

## 9. Organisation des fichiers

```
Dialaw tv/
├── app.py              Routes et logique de l'application
├── database.py         Base SQLite : commandes, mots de passe, appareils
├── utils.py            Téléphones, liens WhatsApp, YouTube, dates
├── config.py           Paramètres et valeurs par défaut
├── templates/          Pages HTML (Jinja2)
│   ├── base.html       Gabarit commun
│   ├── index.html      Page publique
│   ├── commander.html  Formulaire client
│   ├── paiement.html   Instructions Wave
│   ├── suivi.html      Suivi et affichage du mot de passe
│   ├── acces.html      Saisie du mot de passe
│   ├── live.html       Lecteur protégé
│   ├── admin*.html     Back-office
│   └── erreur.html
├── static/style.css    Toute la mise en forme
├── demarrer.bat        Lancement en un double-clic
└── .env                Vos secrets (à créer, jamais publié)
```
