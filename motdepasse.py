"""Change le mot de passe d'un compte du back-office.

    python motdepasse.py

Le compte administrateur n'est créé qu'au tout premier démarrage : modifier
le fichier .env ensuite ne change rien. Ce script agit directement sur la
base, sans avoir à la supprimer ni à perdre vos ventes.
"""

import getpass
import sqlite3
import sys

from werkzeug.security import generate_password_hash

from config import Config

LONGUEUR_MINIMALE = 8


def lister_comptes(connexion):
    return connexion.execute("SELECT id, email FROM admins ORDER BY id").fetchall()


def main():
    try:
        connexion = sqlite3.connect(Config.DATABASE)
        connexion.row_factory = sqlite3.Row
        comptes = lister_comptes(connexion)
    except sqlite3.Error as erreur:
        print(f"\n  Base de donnees illisible : {erreur}")
        print("  Lancez d'abord l'application une fois : python app.py\n")
        return 1

    if not comptes:
        print("\n  Aucun compte administrateur dans la base.")
        print("  Lancez d'abord l'application une fois : python app.py\n")
        return 1

    print("\n  Comptes du back-office :")
    for compte in comptes:
        print(f"    [{compte['id']}] {compte['email']}")

    if len(comptes) == 1:
        choisi = comptes[0]
        print(f"\n  Compte selectionne : {choisi['email']}")
    else:
        saisie = input("\n  Numero du compte a modifier : ").strip()
        correspondances = [c for c in comptes if str(c["id"]) == saisie]
        if not correspondances:
            print("  Numero inconnu. Abandon.\n")
            return 1
        choisi = correspondances[0]

    # getpass masque la frappe : le mot de passe ne reste pas affiche a l'ecran
    nouveau = getpass.getpass("  Nouveau mot de passe : ")
    if len(nouveau) < LONGUEUR_MINIMALE:
        print(f"  Trop court : {LONGUEUR_MINIMALE} caracteres minimum. Abandon.\n")
        return 1

    if nouveau == Config.MOT_DE_PASSE_USINE:
        print("  C'est le mot de passe d'usine, connu de tous. Abandon.\n")
        return 1

    confirmation = getpass.getpass("  Confirmez le mot de passe : ")
    if nouveau != confirmation:
        print("  Les deux saisies different. Abandon.\n")
        return 1

    connexion.execute(
        "UPDATE admins SET mot_de_passe_hash = ? WHERE id = ?",
        (generate_password_hash(nouveau), choisi["id"]),
    )
    connexion.commit()
    connexion.close()

    print(f"\n  Mot de passe de {choisi['email']} mis a jour.")
    print("  Il prend effet immediatement, sans redemarrer l'application.\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Annule.\n")
        sys.exit(1)
