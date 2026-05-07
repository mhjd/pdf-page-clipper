Mon objectif est de pouvoir traduire un pdf d'arabe vers le français, mais c'est pénible de devoir copier coller des screen des pages de pdf, donc j'aimerais automatiser ça.

J'ai besoin d'une app en ligne de commande qui me permet de, à partir d'un pdf, généré des images de chaque page de ce pdf dans un dossier dédier à ce pdf.

J'ai également besoin d'une commande pour copier la n_ième page.
C'est un peu chiant de devoir écrire le nombre de la page en ligne de commande, alors j'aimerais aussi un mode "iterator", où je fais juste commande next, et ça me copie le suivant. La variable d'itération sera enregistrer dans un fichier yml dans le dossier des images du pdf.
il faut aussi une commande "previous" et "current" pour copier l'image présente de nouveau (au cas où on aurait perdu le copiage) ou la précédente (dans le cas où, par erreur, on serait aller sur un next de trop).
Il faut aussi une manière de changer la valeur de la variable d'itération en ligne de commande.

J'ai envie de deux mode : un mode "copier le texte" et un mode "copier l'image", car des fois les pdf sont suffisamment riche côté texte, inutile de faire un screen ce qui alourdit énormément. Je veux pouvoir switch de mode simplement.

L'application doit être très simple à utiliser, pas de format compliquer à retenir, j'imagine un truc en mode : lancer l'application, puis on a des lettre qui permette d'effectuer des opérations (un peu comme les options qui apparaissent quand on fait C-x sur Emacs). Le fait d'aovir des lettres pour lancer des commandes plutôt que devoir écrire à la main est beaucoup plus pratique.

Du coup, pour set, il faut également un mode "entry", et un mode "escape entry" pour retourner à la "page" des raccourcis de commande.

Je veux une application très minimaliste dans son code, élégante conceptuellement, très peu dépendant de third party pour éviter des problèmes de compatibilité. Je veux également si possible limité au max les installation à faire.

Tu as le pdf fleur_du_mal pour faire des tests. 

J'aimerais bien évidemment des informations utile qui s'affiche quand on fait une action. Typiquement, quand on fait next, ça nous affiche le numéro de page copié. Penses à ces problèmes d'expériences utilisateur, c'est important. Typiquement aussi, l'entry, si on va changer le numéro de la variable d'itération, il est pertinent de mettre sa valeur de base dans l'entry. Comme ça, déjà on l'a en tête la valeur actuelle, et ensuite, on peut juste changer un chiffre si le numéro de page est long et que changer un chiffre suffit.
