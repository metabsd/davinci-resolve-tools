# DaVinci Resolve Tools

Outils Python pour **automatiser des tâches répétitives dans DaVinci Resolve** :
insertion de markers, détection de scènes, analyses diverses — chaque outil est
indépendant et vit dans son propre sous-dossier sous `tools/`.

> **Outils disponibles**
> - [`tools/people-detector`](tools/people-detector/) — détecte les présences humaines via YOLO et injecte les timestamps en markers dans le timeline Resolve.

## Pourquoi ce dépôt ?

DaVinci Resolve est puissant mais beaucoup de tâches préparatoires restent
manuelles :
- retrouver toutes les secondes où quelqu'un parle face caméra
- découper aux changements de scène parlante
- nettoyer un long rush avant le dérushage

Ce dépôt regroupe de petits outils Python, **chacun exécutable seul**, qui
s'appuient au choix sur :
- la **DaVinci Resolve Python API** (intégré à DaVinci, gratuit) pour piloter le logiciel
- des libs externes (**Ultralytics YOLO**, **OpenCV**, etc.) pour l'analyse vidéo

## Installation (Windows)

Voir [**docs/INSTALL_WINDOWS.md**](docs/INSTALL_WINDOWS.md) pour le guide complet.

En résumé :
1. Installer **Python 3.10+** (cocher "Add to PATH")
2. Cloner ce repo : `git clone https://github.com/metabsd/davinci-resolve-tools.git`
3. Créer un venv et installer : `pip install -r requirements.txt`
4. Dans DaVinci Resolve : **Settings → System → General → External scripting using : Local** (case à cocher)
5. Lancer un outil, par ex. :
   ```powershell
   python tools/people-detector/detect.py --video "C:\rushs\mon_film.mp4" --output output\mon_film.csv
   ```
6. Pour pousser les markers dans Resolve :
   ```powershell
   "C:\Program Files\Blackmagic Design\DaVinci Resolve\python.exe" tools\people-detector\import_resolve.py --csv output\mon_film.csv
   ```

## Ajouter un nouvel outil

```bash
mkdir tools/mon-outil
touch tools/mon-outil/__init__.py
touch tools/mon-outil/mon_outil.py
tools/mon-outil/README.md    # expliquer l'usage, les inputs, les outputs
```

Convention :
- un outil = un sous-dossier autonome sous `tools/`
- dépendances spécifiques → `tools/mon-outil/requirements.txt` (optionnel)
- s'il pousse des markers dans Resolve → réutilise `shared/resolve_api.py`

## Pré-requis

| Composant | Pourquoi | Notes |
|---|---|---|
| DaVinci Resolve 18.5+ | Cible des outils | Free suffit (markers + Python API). Studio nécessaire pour scripting réseau. |
| Python 3.10+ | Exécution | **NE PAS** utiliser le Python embarqué de Resolve pour les outils — uniquement pour l'import. |
| Git | Pour suivre les mises à jour | Windows : https://git-scm.com |
| GPU NVIDIA (optionnel) | Accélérer YOLO 5–10× | Sans GPU : tout fonctionne, juste plus lentement (CPU only). |

## Roadmap

Voir l'onglet [Issues](https://github.com/metabsd/davinci-resolve-tools/issues).
Idées en vrac :
- `silence-detector` : repère les passages sans parole → candidats à la coupe
- `scene-cuts` : détection de coupes améliorée (combine vision + audio)
- `subtitle-extract` : exporte les sous-titres Resolve en SRT/CSV

## Licence

MIT — voir [LICENSE](LICENSE).
