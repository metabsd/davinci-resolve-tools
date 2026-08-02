# Installation sur Windows — guide complet

Setup pas-à-pas de **DaVinci Resolve Tools** sur Windows 10/11.
Durée : ~20 minutes si tu as déjà Python + Git, plus si tu pars de zéro.

---

## 1. Pré-requis

| Logiciel | Lien | Notes |
|---|---|---|
| **DaVinci Resolve 18.5+** | https://www.blackmagicdesign.com/products/davinciresolve | Free ou Studio |
| **Python 3.10, 3.11 ou 3.12** | https://www.python.org/downloads/windows/ | ⚠️ Cocher **"Add Python to PATH"** à l'install |
| **Git pour Windows** | https://git-scm.com/download/win | Par défaut, ça suffit |
| **VS Code** (déjà installé chez toi) | — | On ne s'en sert pas ici, juste Git Bash ou PowerShell |
| **GPU NVIDIA** + drivers (optionnel) | GeForce Experience | Accélère YOLO 5–10×, **pas obligatoire** |

### Vérifie l'install Python

Ouvre **PowerShell** (tape `powershell` dans la barre de recherche Windows) :

```powershell
python --version
# doit afficher Python 3.10.x, 3.11.x ou 3.12.x

git --version
# doit afficher git version 2.x
```

Si une de ces commandes dit *"command not found"* → réinstalle le logiciel
correspondant en cochant bien la case PATH.

---

## 2. Cloner le repo

Choisis un dossier de travail (par exemple `C:\dev`) :

```powershell
cd C:\dev
git clone https://github.com/metabsd/davinci-resolve-tools.git
cd davinci-resolve-tools
```

---

### 3. Créer le venv et installer les dépendances

```powershell
# Dans C:\dev\davinci-resolve-tools
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> ⚠️ Si PowerShell refuse l'activation avec une erreur "running scripts is disabled",
> exécute une seule fois (en admin) :
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
> puis réessaie `.\.venv\Scripts\Activate.ps1`.

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Premier install : ~2 minutes (Ultralytics télécharge YOLO11n ≈ 6 MB à la première exécution).

### Accélérer YOLO — par type de GPU

Le `requirements.txt` installe déjà **`onnxruntime-directml`** qui couvre **tous
les GPU modernes via DirectX 12** (AMD, Intel, NVIDIA). Pas besoin de drivers
spéciaux : ton driver AMD Adrenalin (fourni par Windows Update) suffit.

| Matériel | Action | Résultat |
|---|---|---|
| **AMD iGPU RDNA 2/3** (ROG Ally X, Steam Deck, Ryzen laptop) | Aucune — `pip install -r requirements.txt` suffit | ~5–10× plus rapide que CPU |
| **AMD Radeon dédié** (RX 6000/7000) | Idem, DirectML suffit | ~10× plus rapide que CPU |
| **Intel Arc / Intel iGPU** | Idem, DirectML suffit | ~5× plus rapide que CPU |
| **NVIDIA GPU** | Ajoute : `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121` | ~10× plus rapide que CPU |
| **CPU only** (vieux laptop sans GPU compatible) | Supprime la ligne `onnxruntime-directml` du `requirements.txt` puis réinstalle | Ralentit, mais fonctionne |

Le détecteur choisit automatiquement le backend au runtime et affiche
`[detect] Using device: dml` au démarrage si ton GPU est utilisé.

---

## 4. Activer le scripting externe dans DaVinci Resolve

Cette étape est **obligatoire** pour que les outils puissent pousser des markers
dans le timeline.

1. Lance **DaVinci Resolve**
2. Menu **DaVinci Resolve → Preferences** (ou `Ctrl+,`)
3. Onglet **System** → section **General**
4. Cocher **☑ External scripting using**
   - Choisir **Local**
5. Valider → fermer Resolve (la prise en compte nécessite un redémarrage complet)

> Vérification rapide : à ce stade, Resolve expose un serveur localhost sur lequel
> `shared/resolve_api.py` se connecte.

---

## 5. Trouver le Python embarqué de Resolve

DaVinci Resolve installe son **propre** interpréteur Python. C'est **celui-là**
qu'on utilise pour piloter Resolve (pas ton venv), parce qu'il contient le
module `DaVinciResolveScript` que ton venv ne peut pas importer.

L'emplacement standard :

```
C:\Program Files\Blackmagic Design\DaVinci Resolve\python.exe
```

Vérifie qu'il existe :

```powershell
Test-Path "C:\Program Files\Blackmagic Design\DaVinci Resolve\python.exe"
# doit afficher True
```

Tu peux aussi simplement lancer cet interpréteur pour voir les modules Resolve :

```powershell
& "C:\Program Files\Blackmagic Design\DaVinci Resolve\python.exe" -c "import DaVinciResolveScript; print('OK')"
# doit afficher OK
```

---

## 6. Tester l'installation

Ouvre n'importe quel projet dans DaVinci Resolve, puis dans **deux terminaux
différents** :

### Terminal 1 — analyser une vidéo

```powershell
cd C:\dev\davinci-resolve-tools
.\.venv\Scripts\Activate.ps1

# Une petite vidéo de test, ~30 secondes
python tools\people-detector\detect.py `
    --video "C:\chemin\vers\ta_video.mp4" `
    --output output\test.csv
```

Si YOLO détecte des gens, tu obtiens un CSV du genre :
```
start,end,confidence
00:00:03.200,00:00:08.500,0.87
00:00:15.100,00:00:22.000,0.91
```

### Terminal 2 — pousser les markers dans Resolve

**Avant cette étape :** dans DaVinci Resolve, importe ta vidéo dans le **Media Pool**, crée une timeline, glisse le clip dessus. Sélectionne le clip.

```powershell
& "C:\Program Files\Blackmagic Design\DaVinci Resolve\python.exe" `
    tools\people-detector\import_resolve.py `
    --csv output\test.csv
```

Va voir Resolve : tu devrais voir les markers colorés sur ton clip,
avec le label de confiance. ✅

---

## 7. Mises à jour

Pour récupérer les dernières versions des outils :

```powershell
cd C:\dev\davinci-resolve-tools
git pull
pip install -r requirements.txt --upgrade
```

---

## Dépannage

| Problème | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'DaVinciResolveScript'` | Tu utilises ton venv au lieu du Python de Resolve | Lance avec `"C:\...\DaVinci Resolve\python.exe"`, pas `python` |
| `Couldn't connect to Resolve` au lancement de l'import | Scripting externe pas activé | Retour étape 4 |
| `RuntimeError: no clip selected in timeline` | Pas de clip sélectionné dans Resolve | Clique le clip dans le timeline avant de lancer l'import |
| YOLO télécharge `yolo11n.pt` à chaque fois | Problème réseau ou cache vidé | Normal la 1ʳᵉ fois, ensuite c'est mis en cache dans `%USERPROFILE%\.cache\ultralytics` |
| `[detect] Using device: cpu` alors que tu as un GPU AMD | `onnxruntime-directml` n'a pas été installé | `pip install onnxruntime-directml` dans ton venv, puis relance |
| `CUDA not available` warnings | Pas de GPU NVIDIA | Ignorer — ça marche quand même en CPU, ou avec DirectML si installé |
| Markers invisibles après import | Resolve Color clip vs audio clip | Sélectionne un clip **vidéo** dans la timeline, pas une piste audio |
| PowerShell refuse l'activation du venv | Execution policy | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
