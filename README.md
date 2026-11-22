# Neuro-Study (Flask) : site + extension navigateur

> **Projet fusionné.** Deux parties qui partagent le même serveur Flask :
> - **L'extension navigateur** (`extension/`) : apprentissage par **Google Meet** et **vidéos YouTube** (sous-titres, traduction, Catch-Up, « Je suis perdu »).
> - **Le site** (`templates/`, `static/`) : apprentissage par **cours écrits et PDF** (blocs par notion, profils neuro, styles d'apprentissage, lecture vocale).
> Côté serveur, `services/pdf_service.py` (découpage des cours) vient du site ; `translate_service.py`, `captions.py` et `knowledge.py` viennent de l'extension.


**Deux parties qui partagent le même serveur :**
- **Le site (app)** : cours écrit/PDF adapté, outils, bilan de séance.
- **L'extension Chrome/Edge** : s'installe sur **Google Meet** et **YouTube** (sous-titres clairs, Catch-Up 15 s, « Je suis perdu », mode calme). Les moments marqués dans l'extension apparaissent dans l'onglet **Bilan** du site.

Assistant d'apprentissage IA pour étudiants : sous-titres/traduction en direct (Derja ↔ FR ↔ EN), détection de décrochage par caméra (100 % locale), profils neuro (TDAH, Dyslexie, Dyscalculie, Autisme), cours PDF avec mémoire visuelle/auditive, et mode démo hors-ligne.

## 1. Installation et lancement

## Lancer le projet : ce qu'il faut écrire dans le terminal

### Sous Windows (PowerShell / terminal de VS Code)

Écrivez ces lignes **une par une**, puis appuyez sur Entrée après chacune (remplacez le chemin par celui de votre dossier) :

```
cd "C:\Users\Yasmine\Documents\Downloads\watat\neuro-study-flask"
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Ouvrez ensuite **http://127.0.0.1:5000** dans Chrome ou Edge.

- La première ligne (`cd ...`) est obligatoire : il faut être dans le dossier `neuro-study-flask`, celui qui contient `app.py` et `requirements.txt`.
- La prochaine fois, il suffit de faire les lignes 1, 4 et 6 (`cd`, `Activate.ps1`, `python app.py`).
- Le message `[notice] A new release of pip is available` n'est pas une erreur.
- Facultatif, pour ajouter une clé IA : `copy .env.example .env`, puis ouvrir `.env` et remplir `GEMINI_API_KEY=`.

### Sous Mac / Linux uniquement

```
cd neuro-study-flask
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Sans clé API, tout fonctionne avec le **repli local** (dictionnaire Derja, résumés par règles). L'onglet **Mode démo** marche sans réseau, sans micro et sans caméra.

### Autres commandes utiles
| But | Commande |
|---|---|
| Lancer en mode production | `gunicorn -w 2 -b 0.0.0.0:5000 app:app` |
| Tester que le serveur répond | `curl http://127.0.0.1:5000/api/health` |
| Tester un sous-titre | `curl -X POST localhost:5000/api/subtitle -H "Content-Type: application/json" -d '{"text":"lyoum bech nechrhou","profile":"tdah"}'` |
| Modèle local gratuit (Ollama) | `ollama pull llama3.2` puis `LLM_PROVIDER=ollama` dans `.env` |
| Transcription serveur (optionnel) | `pip install faster-whisper` (active `/api/transcribe`) |
| Figer les dépendances | `pip freeze > requirements.txt` |
| Vérifier la syntaxe JS | `node --check static/app.js` |
| Ouvrir sur le téléphone (même Wi-Fi) | changer `host="127.0.0.1"` en `"0.0.0.0"` dans `app.py` (micro/caméra exigent HTTPS ou localhost) |

## 2. Arborescence et rôle de chaque fichier

```
neuro-study-flask/
├── app.py                    Point d'entrée Flask : pages + routes API JSON
├── requirements.txt          flask, python-dotenv, requests, pypdf, gunicorn
├── .env.example              Variables d'environnement (clés, modèles, timeout)
├── README.md                 Ce fichier
├── services/
│   ├── ai_service.py         LLM (Gemini/ChatGPT/Claude/Groq/Ollama) + cache + diagnostic + replis :
│   │                         subtitle, catchup, micropulse, simplify, explain_when_lost (« Je suis perdu »)
│   ├── visuals.py            Dessine courbes / enchaînements / comparaisons en SVG sûr à partir d'une spec JSON
│   ├── history_store.py      Historique persistant des points non compris (data/history.json)
│   ├── pdf_service.py        Extraction PDF/TXT, micro-sections, mots-clés
│   ├── youtube_service.py    ID de vidéo, transcription YouTube, segments synchronisés
│   ├── profiles.py           Config des profils (ce qui DIFFÈRE), styles d'apprentissage, chiffres → sens, langage littéral
│   └── session_store.py      Courbe, transcript, bilan « notions à revoir » (mémoire)
├── demo_data/
│   ├── sample_meet.json      Scénario démo (6 étapes : sous-titres, décrochage, Catch-Up, Micro-Pulse)
│   └── sample_course.txt     Cours d'exemple pour l'onglet PDF
├── templates/
│   └── index.html            Interface unique (3 onglets : Cours en direct, PDF, Démo)
├── extension/                Extension Chrome/Edge (Manifest V3)
│   ├── manifest.json         Sites autorisés : Meet, YouTube, serveur local
│   ├── background.js         Relais réseau vers le serveur Flask
│   ├── content.js            Panneau flottant (Shadow DOM) : sous-titres, Catch-Up, Perdu, Micro-Pulse, pauses auto, vitesse
│   └── calm.css              Mode calme (masque colonne latérale, commentaires, pop-ups YouTube)
└── static/
    ├── styles.css            Design + thèmes de profils (TDAH, Dyslexie, Dyscalculie, Autisme)
    ├── app.js                Logique UI : micro, sous-titres, Catch-Up, courbe Chart.js, PDF, TTS, démo
    └── camera_tracker.js     MediaPipe FaceLandmarker local → score d'attention
```

## 3. Routes API

| Méthode | Route | Corps / paramètres | Réponse |
|---|---|---|---|
| GET | `/` | – | Page principale |
| GET | `/api/health` | – | `{ok, llm, providers, errors}` (fournisseurs IA configurés + dernières erreurs) |
| GET | `/api/llm/test` | – | Teste vraiment vos IA : `{ok, provider, errors}` — **à ouvrir en cas de doute** |
| POST | `/api/lost` | `{captions:[{t,text}], current_time, video_id, source_title, platform, url, target, profile, previous?, replace_id?}` | `{id, point, quote, why_hard, prerequisites, paragraph, analogy, example, steps, formula, visual_svg, image, check, provider, fallback, error}` + enregistrement dans l'historique |
| GET | `/api/history` | – | `{items:[{id, created_at, source, video_time, understood, result}]}` |
| POST | `/api/history/<id>/understood` | `{understood}` | entrée mise à jour |
| DELETE | `/api/history/<id>` · POST `/api/history/clear` | – | `{ok}` |
| GET | `/history` | – | Page web de l'historique (toutes les explications, schémas inclus) |
| POST | `/api/subtitle` | `{text, t, source, target, profile}` | `{subtitle, keywords, fallback}` |
| POST | `/api/catchup` | `{context, profile}` | `{text, fallback}` |
| POST | `/api/micropulse` | `{text}` | `{phrase, question, answer, fallback}` |
| POST | `/api/simplify` | `{text, profile}` | `{text, fallback}` |
| POST | `/api/pdf` | `multipart` champ `file` (.pdf ou .txt, 15 Mo max) | `{sections:[{id,title,text,keywords,summary}]}` |
| GET | `/api/pdf/demo` | – | Sections du cours d'exemple |
| GET | `/api/demo` | – | Scénario `sample_meet.json` |
| POST | `/api/youtube/transcript` | `{url}` ou `{url, text}` (transcription collée) | `{video_id, segments:[{start,text}], source}` |
| GET | `/api/profiles` | – | `{profiles, styles}` (config + tableau des différences) |
| POST | `/api/lesson` | `{text, profile, style}` | `{idea, explain, example, check_q, check_a, activity, steps, calc, keywords}` |
| POST | `/api/checklist` | `{task, profile}` | `{steps}` (consigne → checklist) |
| POST | `/api/gaps` | `{text, profile}` | `{gaps:[{prereq, explain}]}` |
| POST | `/api/pack` | `{profile, text?}` (sinon transcription de la séance) | `{summary, terms, questions}` |
| POST | `/api/reexplain` | `{t, notion, profile}` | `{text}` |
| POST | `/api/board` | `multipart` champ `image` (clé Gemini requise) | `{text}` |
| GET | `/api/visual?q=mot` | – | `{image, title, extract}` (Wikipédia, sans clé) |
| POST | `/api/session/meta` | `{source, title, url}` | `{ok}` |
| POST | `/api/session/point` | `{t, attention, label, lost}` | `{ok}` |
| GET | `/api/session/summary` | – | `{points, avg_attention, lost_count, to_review}` |
| POST | `/api/session/reset` | – | `{ok}` |
| POST | `/api/transcribe` | `multipart` champ `audio` | `{text}` (501 si faster-whisper absent) |

`profile` ∈ `standard | tdah | dyslexie | dyscalculie | autisme`. `fallback: true` = réponse produite sans IA.

## 4. Variables d'environnement (`.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `LLM_PROVIDER` | `gemini,openai,claude,groq,ollama` | Ordre d'essai ; un fournisseur sans clé est ignoré (alias : `chatgpt`=openai, `anthropic`=claude) |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | – / `gemini-2.5-flash` | Google Gemini |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | – / `gpt-4o-mini` / `https://api.openai.com/v1` | ChatGPT (ou tout service compatible OpenAI : OpenRouter, LM Studio…) |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | – / `claude-haiku-5-5` | Claude |
| `GROQ_API_KEY` / `GROQ_MODEL` | – / `llama-3.1-8b-instant` | Groq (offre gratuite) |
| `OLLAMA_URL` / `OLLAMA_MODEL` | `http://127.0.0.1:11434` / `llama3.2` | Modèle local |
| `LLM_TIMEOUT` | `8` | Secondes avant de passer au fournisseur suivant (sous-titres) |
| `LLM_LOST_TIMEOUT` | `30` | Idem pour « Je suis perdu » (réponse plus longue) |
| `WHISPER_MODEL` | `tiny` | Modèle faster-whisper (`tiny` ou `base`) |

Vérifiez les noms de modèles : les offres gratuites changent.

## 5. Fonctionnalités et où les trouver

- **Sous-titres / traduction** : bouton « Démarrer le micro » (Web Speech API, Chrome/Edge) → `/api/subtitle`. Choix langue parlée (FR, Derja/arabe, EN) et langue des sous-titres.
- **Catch-Up 15 s** : résume les 15 dernières secondes. Se déclenche aussi avec « Je suis perdu » et lors d'un décrochage détecté.
- **Caméra / courbe « Déclic Live »** : bouton « Activer la caméra ». Score d'attention lissé, un point toutes les 5 s annoté de la notion du moment, décrochages en rouge. Aucune vidéo n'est envoyée.
- **Notions à revoir** : bilan de séance (`/api/session/summary`).
- **Profils** : sélecteur en haut, modifiable à tout moment (mémorisé dans le navigateur).
  - TDAH : Micro-Pulse (bouton + auto toutes les 3 min), Pause recentrage 30 s, sous-titres courts.
  - Dyslexie : police Lexend, interligne et espacement élargis, fond doux, bouton « Lire à voix haute ».
  - Dyscalculie : explications qualitatives, étapes numérotées.
  - Autisme : interface calme, aucune animation, reformulation littérale.
- **Cours PDF** : onglet « Cours écrit (PDF) » → import ou cours d'exemple. Mots-clés surlignés (mémoire visuelle), « Lire avec emphase » (mémoire auditive), « Simplifier » selon le profil.
- **Vidéo YouTube** : onglet « Cours en direct » → coller le lien → « Charger la vidéo ». Le lecteur s'affiche ; pendant la lecture, sous-titres, Catch-Up 15 s, « Je suis perdu » et la courbe suivent le temps de la vidéo. Si YouTube n'a pas de transcription, cliquer « Coller une transcription ». Régler « Langue parlée » sur la langue de la vidéo.
- **Mode démo** : onglet « Mode démo » → Lecture / Pause / Suivant / Recommencer (3,5 s par étape).

## 5 bis. Extension navigateur

**Installation (Chrome ou Edge)**
1. Lancez le serveur : `python app.py` (avec au moins une clé IA dans `.env`).
2. `chrome://extensions` → **Mode développeur** → **Charger l'extension non empaquetée** → dossier `extension/`.
3. Après chaque modification du code : bouton ⟳ de l'extension **puis** recharger l'onglet YouTube/Meet.
4. Ouvrez une vidéo YouTube ou un Google Meet : le panneau **Neuro-Study** apparaît à droite. La pastille doit afficher « Connecté · IA gemini » (ou openai, claude…).

**Bouton « Je suis perdu »**
1. Il récupère ce qui vient d'être dit : transcription YouTube autour de l'instant exact (même sans sous-titres CC) + sous-titres lus à l'écran.
2. L'IA repère **le point précis** non compris (la dernière idée difficile, pas le sujet général) et répond en plusieurs supports : citation de la vidéo, pourquoi c'est difficile, explication simple, analogie, exemple, étapes, formule, **schéma / courbe / comparaison** (dessinés par `services/visuals.py`), image Wikipédia, mini-question de vérification.
3. Boutons : **J'ai compris**, **↻ Expliquer autrement** (nouvelle explication, autre angle), **▶ Reprendre** (la vidéo est mise en pause automatiquement, option désactivable).
4. Chaque clic est gardé dans l'onglet **Historique** (point, instant ⏱ cliquable, explication complète, statut compris/à revoir), exportable en Markdown, et visible sur http://127.0.0.1:5000/history. Le fichier est `data/history.json`.

**Score « Compréhension ≈ X % »** : estimation (pas une mesure médicale), calculée sur les 5 dernières minutes :
attention caméra (100 % locale, aucune image envoyée) − 10 pts par « Je suis perdu » − 5 pts par retour en arrière dans la vidéo. Sans caméra, la base est 80 %. Survolez la pastille pour voir le détail. Si le score reste bas 15 s, le bouton « Je suis perdu » se met à clignoter (l'IA n'est jamais appelée sans votre clic).

La caméra utilise l'API `FaceDetector` du navigateur si elle existe, sinon une analyse simple (présence du visage, tête tournée, agitation). Pour un suivi du regard plus fin, il faudrait embarquer MediaPipe dans le dossier `extension/` (Manifest V3 interdit le code distant).

**Limites connues**
- Meet change souvent son code : si les sous-titres ne sont pas lus, ajustez les sélecteurs dans `extractLiveCaption()` (`extension/content.js`).
- La transcription YouTube automatique dépend de `youtube-transcript-api` ; sans elle, l'aide utilise les sous-titres CC affichés.
- Serveur déployé en ligne : ajoutez son adresse dans `host_permissions` du `manifest.json` et `API_BASE` de `background.js`.

## 5 ter. Profils neuro et styles d'apprentissage

Deux réglages indépendants :
- **Profil** = *comment le contenu est traité* (texte, chiffres, rythme).
- **Style** = *comment il est présenté* (images, audio, notes, pratique).

| Profil | Interface | Texte | Chiffres | Rythme |
|---|---|---|---|---|
| Standard | Par défaut | Blocs d'environ 90 mots | Conservés | Libre |
| TDAH | Thème sombre, idée-clé en grand | Micro-blocs d'environ 40 mots, un seul visible, « Bloc suivant » | Conservés | Micro-Pulse 3 min, focus 12 min puis pause de recentrage |
| Dyslexie | Lexend, interligne double, fond crème | Mots simples | Conservés | Lecture vocale avec emphase, bouton « Écouter » |
| Dyscalculie | Calculs masqués (« Voir le calcul ») | Raisonnement d'abord | **Traduits en sens** (0,3 → un peu moins qu'un tiers) | Étapes dans l'ordre |
| Autisme | Calme, aucun mouvement | **Littéral** (« coup de main » → « aide »), étapes numérotées | Conservés | Plan du cours visible, rien ne s'ouvre seul, Micro-Pulse à la demande |

| Style | Rendu d'un bloc de cours |
|---|---|
| Visuel | Image Wikipédia du mot-clé, carte mentale, mots-clés surlignés |
| Auditif | Lecture vocale (emphase sur les mots-clés), texte masqué par défaut, vitesse réglable, « Lecture continue » |
| Lecture/écriture | Notes à puces, glossaire, zone « Mon résumé en une phrase » |
| Pratique | Action à faire d'abord, question de vérification, explication en option |

Chaque bloc suit la même structure : **idée en une ligne → explication → exemple → vérification**.

**Outils** (onglet Outils) : décomposer une consigne en checklist, trouver les prérequis manquants, photo du tableau → notes (clé Gemini).

## 5 quater. Traduction des sous-titres (français / English / العربية)

Le sous-titre s'affiche **dans la langue choisie**, le texte d'origine reste visible en petit dessous.

| Où | Comment ça marche |
|---|---|
| Site (`/`) | « Sous-titres en » : les phrases de la vidéo sont traduites **par lots à l'avance** (30 phrases d'avance), donc aucun délai. Changer de langue retraduit tout de suite le sous-titre affiché. |
| Extension YouTube | La transcription est récupérée par le serveur, traduite par lots et **affichée sur la vidéo**, synchronisée avec le temps de lecture (pas besoin d'activer les CC YouTube). |
| Extension Meet | Sous-titres de la réunion (activer **CC** dans Meet) traduits en direct, au plus 1 requête toutes les 3 s. |

Chaîne de secours (`services/translate_service.py`), la traduction ne s'arrête jamais :
1. IA par lots (1 requête pour 10 phrases, comprend le derja tunisien) ;
2. traducteurs gratuits sans clé (Google « gtx », puis MyMemory) : utile si la clé IA ne marche pas ;
3. petit dictionnaire derja → français.

Une phrase déjà dans la langue choisie n'est jamais retraduite, et chaque traduction est mise en cache.
Route : `POST /api/translate_batch {texts:[...], target:"fr|en|ar"}` ; `POST /api/subtitle` renvoie maintenant **uniquement la traduction** (`subtitle`) et garde l'original dans `original`.

> **Si « l'IA ne travaille pas »** : le modèle par défaut `gemini-2.5-flash` ne répond plus aux nouvelles clés (404). Laissez `GEMINI_MODEL=` vide dans `.env` : le serveur essaie les modèles récents puis demande à Google la liste réelle. Testez avec `http://127.0.0.1:5000/api/llm/test`.

## 6. Architecture en bref

- **Replis** : chaque fonction IA renvoie toujours un résultat (`fallback: true` si pas de LLM).
- **Cache** : 500 réponses LLM en mémoire.
- **Disjoncteur** : un fournisseur en erreur est ignoré 60 s.
- **Session** : stockée en mémoire, remise à zéro au redémarrage (`SessionStore.dump()` écrit `session_dump.json` si besoin).

## 7. Répartition à 3 personnes

| Dev | Fichiers |
|---|---|
| 1 : Backend + IA + PDF | `app.py`, `services/*`, `demo_data/*` |
| 2 : Live + caméra + courbe | `static/app.js`, `static/camera_tracker.js` |
| 3 : Profils + PDF UI + démo | `templates/index.html`, `static/styles.css`, scénario `sample_meet.json` |

## 8. Script de démo (3 min)

1. Onglet **Mode démo** → Lecture : sous-titres Derja → français, la courbe se remplit.
2. À 01:14, décrochage sur « corrélation négative » : Catch-Up affiché.
3. Changer le profil (TDAH puis Dyscalculie) : l'interface et les explications changent.
4. Onglet **PDF** → cours d'exemple → « Lire avec emphase » puis « Simplifier ».
5. Retour onglet Live → « Notions à revoir » pour le bilan.

## 9. Dépannage

| Problème | Solution |
|---|---|
| Micro ne démarre pas | Utiliser Chrome/Edge, autoriser le micro, ouvrir via `localhost` |
| « Je suis perdu » donne une réponse générique / « IA indisponible » | Ouvrir http://127.0.0.1:5000/api/llm/test : affiche quelle IA répond, ou l'erreur exacte (clé invalide, quota 429, modèle inexistant…) |
| Pastille « Flask éteint » | Lancer `python app.py` ; vérifier que l'extension a bien été rechargée (⟳) |
| Caméra refusée ou lente | Autoriser la caméra ; sinon utiliser « Je suis perdu » ou le Mode démo |
| Chart ou MediaPipe ne charge pas | Ces bibliothèques viennent d'un CDN : ouvrir la page une fois avec du réseau |
| Sous-titres pas traduits | Pas de clé valide → repli local limité ; vérifier `.env` et `/api/health` |
| PDF « aucun texte trouvé » | PDF scanné (image) : utiliser un PDF texte ou un `.txt` |
| `ModuleNotFoundError` | Activer le venv puis `pip install -r requirements.txt` |
| « Transcription indisponible » | Vidéo sans sous-titres ou accès bloqué : « Coller une transcription » (lien + texte) |
| `pip install youtube-transcript-api` | Nécessaire pour la transcription automatique (déjà dans `requirements.txt`) |
| Port 5000 occupé | Changer `port=5000` dans `app.py` |

## Meet : lecture des sous-titres (correctif)

- `extension/meet_captions.js` lit **uniquement** la zone « Sous-titres » de Meet, ignore boutons/icônes/infobulles et l'interface de l'extension, et découpe par intervenant.
- Si les sous-titres Meet sont éteints, la barre latérale le dit et propose « Activer les sous-titres » (une tentative automatique au chargement).
- `services/captions.py` nettoie aussi côté serveur (sécurité si une ancienne version de l'extension envoie du bruit).
- Tests : `node tests/test_meet_captions.js` et `python tests/test_meet_backend.py`.
- Ollama local : `OLLAMA_TIMEOUT`, `OLLAMA_KEEP_ALIVE` (voir `.env.example`). Pour des réponses rapides, mettre une clé gratuite Groq ou Gemini.

## Découpage du cours (PDF/TXT) : un bloc = une notion
`services/pdf_service.py` ne coupe **jamais** au milieu d'une phrase ou d'une puce.
1. **Nettoyage** : mots coupés en fin de ligne recollés, ligatures corrigées, en-têtes/pieds de page et numéros supprimés, paragraphes reconstruits (y compris d'une page à l'autre).
2. **Structure** : titres numérotés, MAJUSCULES et titres courts repérés ; les puces restent avec leur phrase d'introduction.
3. **Un bloc par notion** : un nouveau titre ou une nouvelle définition (« X est… », « On appelle X… », « Définition : … ») démarre un nouveau bloc. Un paragraphe trop long est coupé entre deux phrases entières. Un bloc trop court est rattaché au précédent.
4. **Titre et mots-clés** : titre du cours si présent, sinon « Définition : terme » ou le début de la phrase. Mots-clés = terme défini, expressions répétées, sigles.
Le réglage par profil (`chunk_words`) est un **objectif souple** : un paragraphe complet jusqu'à 2× cette taille reste entier.
