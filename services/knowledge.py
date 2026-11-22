"""Mode secours HORS-LIGNE de « Je suis perdu » : explications prêtes à l'emploi (sans IA, sans réseau).

Quand aucune IA ne répond (clé absente, quota, panne Wi-Fi pendant la démo), on reconnaît quand même la notion
dans ce qui vient d'être dit et on donne : explication simple, analogie, exemple, étapes, formule, schéma, question.
Les textes sont écrits en français ; ai_service les traduit vers la langue choisie si un traducteur est joignable.
Pour ajouter une notion : copier une entrée de CONCEPTS (mots-clés `keys` en minuscules, sans accent).
"""
import re
import unicodedata

CONCEPTS = [
    {
        "id": "moyenne",
        "keys": ["moyenne", "mean", "average", "المتوسط", "المعدل", "wost"],
        "point": "La moyenne",
        "why_hard": "On la confond souvent avec la valeur du milieu (la médiane).",
        "paragraph": "La moyenne résume plusieurs nombres en un seul. On additionne toutes les valeurs, puis on divise "
                     "par le nombre de valeurs. C'est la part que chacun aurait si tout était partagé équitablement.",
        "analogy": "4 amis se partagent équitablement 20 bonbons : chacun en reçoit 5. Ce 5 est la moyenne.",
        "example": "Notes : 10, 12 et 14. La somme vaut 36 et il y a 3 notes, donc la moyenne est 36 ÷ 3 = 12.",
        "steps": ["Additionne toutes les valeurs.", "Compte combien il y a de valeurs.", "Divise la somme par ce nombre."],
        "formula": "moyenne = somme des valeurs ÷ nombre de valeurs",
        "prerequisites": ["Addition", "Division"],
        "visual": {"type": "flow", "title": "Calculer une moyenne", "nodes": ["Additionner", "Compter", "Diviser"]},
        "check": {"question": "Quelle est la moyenne de 2, 4 et 9 ?", "answer": "(2 + 4 + 9) ÷ 3 = 5."},
    },
    {
        "id": "ecart-type",
        "keys": ["ecart-type", "ecart type", "ecarttype", "standard deviation", "الانحراف المعياري", "dispersion",
                 "disperse", "mbaajdin", "variance"],
        "point": "L'écart-type",
        "why_hard": "Il ne dit pas où sont les valeurs (ça, c'est la moyenne) mais à quel point elles s'étalent.",
        "paragraph": "L'écart-type mesure à quel point les valeurs sont éparpillées autour de la moyenne. "
                     "S'il est petit, les valeurs sont proches les unes des autres. S'il est grand, elles sont très étalées.",
        "analogy": "Deux classes ont 12 de moyenne. Dans la première tout le monde a entre 11 et 13. Dans la seconde, "
                   "certains ont 4 et d'autres 20. La seconde a le plus grand écart-type.",
        "example": "Série A : 11, 12, 13 (groupées, écart-type faible). Série B : 4, 12, 20 (éloignées, écart-type fort). "
                   "Les deux séries ont pourtant la même moyenne : 12.",
        "steps": ["Calcule la moyenne.", "Regarde de combien chaque valeur s'écarte de cette moyenne.",
                  "Fais une sorte de moyenne de ces écarts : c'est l'écart-type."],
        "formula": "écart-type = √( moyenne des (valeur − moyenne)² )",
        "prerequisites": ["La moyenne"],
        "visual": {"type": "comparison", "title": "Écart-type faible ou fort",
                   "left": {"title": "Faible", "items": ["Valeurs groupées", "11 · 12 · 13"]},
                   "right": {"title": "Fort", "items": ["Valeurs étalées", "4 · 12 · 20"]}},
        "check": {"question": "Deux séries ont la même moyenne. L'une a un écart-type de 1, l'autre de 8. "
                              "Laquelle est la plus étalée ?", "answer": "Celle dont l'écart-type vaut 8."},
    },
    {
        "id": "correlation",
        "keys": ["correlation", "correle", "الارتباط", "lien entre", "causalite", "wa7da tla3", "tnez"],
        "point": "La corrélation",
        "why_hard": "Deux choses qui varient ensemble ne sont pas forcément liées par une cause.",
        "paragraph": "La corrélation décrit le lien entre deux quantités. Positive : quand l'une augmente, l'autre augmente "
                     "aussi. Négative : quand l'une augmente, l'autre diminue. Attention : corrélation ne veut pas dire cause.",
        "analogy": "Plus il fait chaud, plus on achète de glaces (positive). Plus il fait chaud, moins on porte de manteaux "
                   "(négative).",
        "example": "Heures de sommeil et fatigue : plus on dort peu, plus la fatigue augmente. C'est une corrélation négative.",
        "steps": ["Choisis deux quantités.", "Regarde si elles montent ensemble (positive) ou si l'une monte pendant que "
                  "l'autre descend (négative).", "Ne conclus pas à une cause : un troisième facteur peut expliquer les deux."],
        "formula": "r proche de +1 : positive · r proche de −1 : négative · r proche de 0 : pas de lien",
        "prerequisites": ["Variable", "Courbe"],
        "visual": {"type": "curve", "title": "Deux types de corrélation", "x_label": "Quantité A", "y_label": "Quantité B",
                   "series": [{"name": "Positive", "points": [[0, 1], [1, 2], [2, 3], [3, 4]]},
                              {"name": "Négative", "points": [[0, 4], [1, 3], [2, 2], [3, 1]]}]},
        "check": {"question": "Plus on s'entraîne, moins on met de temps à courir 1 km. Corrélation positive ou négative ?",
                  "answer": "Négative : l'une augmente (entraînement), l'autre diminue (temps)."},
    },
    {
        "id": "probabilite",
        "keys": ["probabilite", "probability", "الاحتمال", "احتمال", "chance", "hasard", "aleatoire", "événement"],
        "point": "La probabilité",
        "why_hard": "Il faut bien distinguer les cas favorables de tous les cas possibles.",
        "paragraph": "Une probabilité mesure la chance qu'un événement arrive. Elle va de 0 (impossible) à 1 (certain). "
                     "On la calcule en comparant les cas qui nous intéressent à tous les cas possibles.",
        "analogy": "Dans un sac de 10 billes dont 3 rouges, tirer une bille rouge a 3 chances sur 10.",
        "example": "Un dé à 6 faces : obtenir un 4 correspond à 1 cas favorable sur 6 cas possibles, donc une probabilité de 1/6.",
        "steps": ["Compte tous les cas possibles.", "Compte les cas qui t'intéressent.", "Divise : cas favorables ÷ cas possibles."],
        "formula": "P = cas favorables ÷ cas possibles",
        "prerequisites": ["Fractions"],
        "visual": {"type": "flow", "title": "Calculer une probabilité", "nodes": ["Tous les cas", "Cas favorables", "Diviser"]},
        "check": {"question": "Pile ou face : quelle est la probabilité d'obtenir pile ?", "answer": "1 cas favorable sur 2, soit 1/2."},
    },
    {
        "id": "fonction",
        "keys": ["fonction", "function", "دالة", "f(x)", "antecedent", "image de"],
        "point": "La fonction",
        "why_hard": "La notation f(x) fait croire à une multiplication alors que c'est « le résultat de la règle pour x ».",
        "paragraph": "Une fonction est une machine : tu lui donnes un nombre (l'entrée x) et, en suivant une règle, elle te "
                     "rend toujours un seul nombre (la sortie f(x)).",
        "analogy": "Un distributeur automatique : tu appuies sur un bouton (entrée) et tu reçois toujours le même produit (sortie).",
        "example": "f(x) = 2x + 1. Si x = 3, alors f(3) = 2 × 3 + 1 = 7.",
        "steps": ["Repère la règle (ici : double, puis ajoute 1).", "Remplace x par la valeur donnée.", "Calcule le résultat."],
        "formula": "f(x) = règle appliquée à x",
        "prerequisites": ["Variable", "Opérations de base"],
        "visual": {"type": "curve", "title": "f(x) = 2x + 1", "x_label": "x", "y_label": "f(x)",
                   "series": [{"name": "f(x)", "points": [[0, 1], [1, 3], [2, 5], [3, 7]]}]},
        "check": {"question": "Avec f(x) = 2x + 1, que vaut f(5) ?", "answer": "2 × 5 + 1 = 11."},
    },
    {
        "id": "derivee",
        "keys": ["derivee", "dérivée", "derivative", "مشتقة", "مشتق", "pente", "tangente", "taux de variation"],
        "point": "La dérivée",
        "why_hard": "Elle décrit un changement « à un instant précis », ce qui est moins intuitif qu'un changement moyen.",
        "paragraph": "La dérivée mesure à quelle vitesse une quantité change à un instant précis. Sur la courbe, c'est la pente "
                     "en ce point : positive si ça monte, négative si ça descend, nulle si c'est plat.",
        "analogy": "Le compteur de vitesse d'une voiture : il indique la vitesse à cet instant, pas la vitesse moyenne du trajet.",
        "example": "Si la distance est d(t) = t², la vitesse à l'instant t est d'(t) = 2t. À t = 3 secondes, la vitesse est 6 m/s.",
        "steps": ["Regarde de combien la quantité change quand x augmente un tout petit peu.",
                  "Divise ce changement par ce petit pas.", "Fais tendre le pas vers 0 : tu obtiens la dérivée."],
        "formula": "f'(x) = lim [f(x+h) − f(x)] ÷ h quand h → 0",
        "prerequisites": ["Fonction", "Pente d'une droite"],
        "visual": {"type": "curve", "title": "La pente change le long de la courbe", "x_label": "x", "y_label": "f(x) = x²",
                   "series": [{"name": "f(x) = x²", "points": [[0, 0], [1, 1], [2, 4], [3, 9]]}]},
        "check": {"question": "Si la dérivée est négative, la courbe monte ou descend ?", "answer": "Elle descend."},
    },
    {
        "id": "equation",
        "keys": ["equation", "équation", "معادلة", "inconnue", "resoudre", "résoudre"],
        "point": "L'équation",
        "why_hard": "Il faut penser à toujours faire la même opération des deux côtés du signe égal.",
        "paragraph": "Une équation est une égalité avec une inconnue (souvent x). La résoudre, c'est trouver la valeur de x qui "
                     "rend l'égalité vraie, en faisant la même opération des deux côtés.",
        "analogy": "Une balance en équilibre : ce que tu enlèves d'un plateau, tu l'enlèves de l'autre pour qu'elle reste droite.",
        "example": "2x + 3 = 11. On enlève 3 des deux côtés : 2x = 8. On divise par 2 des deux côtés : x = 4.",
        "steps": ["Isole le terme avec x (enlève ce qui l'accompagne).", "Fais toujours la même opération des deux côtés.",
                  "Vérifie : remplace x par ta réponse."],
        "formula": "ax + b = c  donc  x = (c − b) ÷ a",
        "prerequisites": ["Opérations inverses"],
        "visual": {"type": "flow", "title": "Résoudre une équation", "nodes": ["Équation", "Même opération des 2 côtés", "x trouvé"]},
        "check": {"question": "Résous x + 5 = 9.", "answer": "x = 4 (on enlève 5 des deux côtés)."},
    },
    {
        "id": "regression",
        "keys": ["regression", "régression", "انحدار", "droite de regression", "nuage de points", "moindres carres"],
        "point": "La régression linéaire",
        "why_hard": "On ne cherche pas à passer par tous les points, mais au plus près de l'ensemble.",
        "paragraph": "La régression linéaire cherche la droite qui passe au plus près d'un nuage de points. Avec cette droite, "
                     "on peut prédire une valeur quand on connaît l'autre.",
        "analogy": "Tracer à l'œil une droite au milieu des points pour deviner où tomberait un nouveau point.",
        "example": "Heures de révision (x) et note (y) : la droite y = 2x + 8 prédit qu'après 5 heures de révision la note sera 18.",
        "steps": ["Place les points (x, y).", "Trouve la droite qui s'éloigne le moins de l'ensemble des points.",
                  "Utilise son équation y = ax + b pour prédire."],
        "formula": "y = ax + b",
        "prerequisites": ["Fonction affine", "Corrélation"],
        "visual": {"type": "curve", "title": "Droite de régression", "x_label": "Heures de révision", "y_label": "Note",
                   "series": [{"name": "y = 2x + 8", "points": [[0, 8], [2, 12], [4, 16], [6, 20]]}]},
        "check": {"question": "Avec y = 2x + 8, que prédit-on pour x = 3 ?", "answer": "y = 2 × 3 + 8 = 14."},
    },
]


def norm(s):
    """minuscules, sans accents ni voyelles arabes, espaces simples."""
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def find(context, focus=""):
    """Notion la plus probablement visée : le terme précisé par l'étudiant, sinon la mention la plus RÉCENTE du contexte."""
    for text in (focus, context):
        t = norm(text)
        if not t.strip():
            continue
        best, best_pos = None, -1
        for c in CONCEPTS:
            for k in c["keys"]:
                pos = t.rfind(norm(k))
                if pos > best_pos:
                    best, best_pos = c, pos
        if best:
            return best
    return None
