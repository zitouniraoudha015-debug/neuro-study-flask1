"""Profils neuro (comment le traitement DIFFÈRE), styles d'apprentissage, transformations déterministes."""
import re


def P(label, chunk, pulse, focus, theme, reveal, literal, qual, prompt, ui, text, numbers, pace, help, description=""):
    return dict(label=label, chunk_words=chunk, pulse_min=pulse, focus_min=focus, theme=theme, reveal=reveal,
                literal=literal, qualitative=qual, prompt=prompt,
                description=description,
                diff=dict(ui=ui, text=text, numbers=numbers, pace=pace, help=help))


PROFILES = {
    "standard": P("Standard", 90, 0, 0, "light", "all", False, False,
                  "Utilise un français clair, des phrases complètes et une explication équilibrée.",
                  "Cadre clair, neutre et équilibré",
                  "Texte confortable avec des blocs complets d'environ 90 mots",
                  "Chiffres présentés clairement avec leur contexte",
                  "Rythme libre, avec une progression simple",
                  "Outils facultatifs : résumé, vérification, lecture audio et aide immédiate",
                  "Une expérience d'apprentissage équilibrée et flexible, avec des explications structurées, une lecture confortable et des outils accessibles à tout moment. Avancez à votre rythme et choisissez l'aide dont vous avez besoin."),
    "tdah": P("TDAH", 40, 3, 12, "dark", "one", False, False,
              "Présente une seule idée principale à la fois, avec des phrases courtes. Mets le mot-clé au début et indique clairement la prochaine action.",
              "Hiérarchie claire, thème sombre doux et contenu focalisé",
              "Sections courtes d'environ 40 mots, une notion visible à la fois",
              "Chiffres conservés et regroupés près de leur explication",
              "Progression visible, Micro-Pulse toutes les 3 minutes et pause de recentrage",
              "Ces repères réduisent la surcharge et facilitent le retour au point d'étude",
              "Des contenus découpés en petites étapes, des objectifs visibles et une interface qui met l'essentiel en évidence. Limitez les distractions, gardez un repère de progression et reprenez facilement là où vous vous êtes arrêté."),
    "dyslexie": P("Dyslexie", 70, 0, 0, "cream", "all", False, False,
                  "Utilise des mots courants, des phrases courtes et des paragraphes aérés. Évite le jargon, les doubles négations et les lignes trop longues.",
                  "Lecture confortable : police Lexend, fond crème et espaces ouverts",
                  "Texte plus grand, interligne double, lettres espacées et alignement à gauche",
                  "Chiffres conservés, séparés des explications quand ils peuvent prêter à confusion",
                  "Lecture vocale contrôlée avec lecture, pause, reprise et volume",
                  "Ces réglages réduisent l'effort de lecture et permettent de suivre le cours à son rythme",
                  "Un environnement de lecture plus confortable avec des caractères faciles à distinguer, des lignes aérées, des paragraphes courts et des notions clairement séparées. Alternez entre lecture et écoute, avec une vitesse et un volume adaptés à votre confort."),
    "dyscalculie": P("Dyscalculie", 70, 0, 0, "light", "all", False, True,
                     "Sépare la raison, la formule, le calcul et le résultat. Explique chaque symbole et chaque nombre avec des mots simples.",
                     "Raisonnement guidé et opérations présentées par étapes",
                     "Phrases courtes avec une séparation claire entre explication et calcul",
                     "Traduits en sens lorsque cela aide, sans supprimer les valeurs utiles",
                     "Étapes numérotées, alignement stable et progression logique",
                     "Ces repères rendent chaque opération plus facile à anticiper et à vérifier",
                     "Les nombres, formules et opérations sont présentés de manière progressive. Chaque calcul est détaillé, les étapes sont séparées et les résultats sont accompagnés d'explications pour comprendre le raisonnement, pas seulement retenir la réponse."),
    "autisme": P("Autisme", 60, 0, 0, "calm", "plan", True, False,
                 "Utilise un langage littéral et explicite. Donne toujours l'étape actuelle, la prochaine étape et les conséquences attendues.",
                 "Cadre calme, stable et entièrement prévisible",
                 "Texte structuré, titres constants, expressions ambiguës évitées",
                 "Chiffres conservés à proximité de leur unité et de leur calcul",
                 "Plan visible, étapes numérotées et aucune interaction automatique",
                 "Ces indications permettent de savoir où l'on se trouve et quoi faire ensuite",
                 "Un parcours organisé avec des repères constants, des consignes explicites et des étapes annoncées. La structure reste stable, les informations sont formulées clairement et aucune animation ou action inattendue ne vient interrompre votre apprentissage."),
}

# Consignes données à l'IA : deux jeux, pour ne rien changer au comportement des deux parties.
#   "prompt"      : extension Meet / YouTube (sous-titres, Catch-Up, « Je suis perdu »)
#   "prompt_site" : site (cours écrits / PDF : leçon, simplification, outils)
_EXT_PROMPTS = {'standard': 'Style clair et concis.',
 'tdah': 'Phrases de 12 mots maximum, une seule idée par phrase, le mot-clé en premier, aucun paragraphe.',
 'dyslexie': 'Mots courts et courants, phrases courtes, aucun jargon, aucune double négation.',
 'dyscalculie': 'Aucun chiffre ni formule : explique avec des mots qualitatifs. Sépare le raisonnement du '
                'calcul.',
 'autisme': 'Langage littéral : aucune métaphore, ironie ni expression ambiguë. Plan clair en étapes.'}
for _k, _v in PROFILES.items():
    _v["prompt_site"] = _v["prompt"]
    _v["prompt"] = _EXT_PROMPTS.get(_k, _v["prompt"])


STYLES = {
    "visuel": {"label": "Visuel", "desc": "Mots-clés visibles, illustrations à la demande et organisation claire du contenu"},
    "auditif": {"label": "Auditif", "desc": "Lecture vocale contrôlée avec pause, reprise et réglage du volume"},
    "lecture": {"label": "Lecture/écriture", "desc": "Notes structurées, glossaire et place pour écrire une synthèse"},
    "pratique": {"label": "Pratique", "desc": "Une action simple à réaliser, puis une explication et une vérification"},
}

LITERAL = {"un coup de main": "une aide", "coup de main": "aide", "en un clin d'œil": "très vite", "c'est du gâteau": "c'est facile",
           "tomber dans les pommes": "perdre connaissance", "poser un lapin": "ne pas venir au rendez-vous",
           "mettre son grain de sel": "donner son avis sans qu'on le demande", "casser du sucre": "dire du mal",
           "avoir le cafard": "être triste", "ça coûte les yeux de la tête": "c'est très cher",
           "pas de panique": "ne t'inquiète pas", "plus ou moins": "à peu près", "on verra": "nous déciderons plus tard",
           "tout à l'heure": "dans quelques heures ou minutes", "je vous laisse": "je vous demande de faire seuls",
           "à vos stylos": "prenez un stylo et écrivez", "ça marche": "c'est d'accord"}

FRACS = [(0.0, "presque rien"), (0.1, "environ un dixième"), (0.25, "un quart"), (1 / 3, "un tiers"), (0.5, "la moitié"),
         (2 / 3, "deux tiers"), (0.75, "trois quarts"), (0.9, "presque tout"), (1.0, "la totalité")]


def _frac(x):
    x = min(max(x, 0.0), 1.0)
    val, name = min(FRACS, key=lambda f: abs(f[0] - x))
    if name.startswith(("environ", "presque")) or abs(x - val) < 0.03:
        return name
    more = x > val
    pre = "un peu plus " if more else "un peu moins "
    return pre + ("qu'" + name if name.startswith("un ") else "que " + name)


def qualitative_numbers(text):
    """30 % → un peu moins qu'un tiers ; 0,3 → idem ; 1/4 → un quart."""
    text = re.sub(r"(\d+(?:[.,]\d+)?)\s?%", lambda m: _frac(float(m.group(1).replace(",", ".")) / 100), text)
    text = re.sub(r"\b(\d+)/(\d+)\b", lambda m: _frac(int(m.group(1)) / int(m.group(2))) if 0 < int(m.group(2)) and int(m.group(1)) <= int(m.group(2)) else m.group(0), text)
    return re.sub(r"\b0[.,]\d+\b", lambda m: _frac(float(m.group(0).replace(",", "."))), text)


def literalize(text):
    for k, v in LITERAL.items():
        text = re.sub(re.escape(k), v, text, flags=re.I)
    return text


def has_math(s):
    return bool(re.search(r"\d|[=+×÷^√]", s))
