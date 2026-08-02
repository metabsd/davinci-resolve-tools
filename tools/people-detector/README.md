# people-detector

Détecte les présences humaines dans une vidéo (via [YOLO11](https://docs.ultralytics.com/))
et injecte les timestamps en **markers dans le timeline DaVinci Resolve**.

## Workflow

```
  ┌─────────────────┐    CSV    ┌──────────────────┐
  │   detect.py     │ ────────► │ import_resolve.py│ ──► Timeline Resolve
  │ (YOLO + OpenCV) │           │ (Resolve Python  │     avec markers "person 0.87"
  └─────────────────┘            │       API)        │
           ▲                     └──────────────────┘
   ton venv Python                Python embarqué de Resolve
```

## Usage

### 1. Analyser une vidéo

```powershell
# Active ton venv
.\.venv\Scripts\Activate.ps1

python tools\people-detector\detect.py `
    --video "C:\rushs\mon_film.mp4" `
    --output output\mon_film.csv
```

Arguments :

| Flag | Description | Défaut |
|---|---|---|
| `--video`, `-v` | Vidéo d'entrée | (requis) |
| `--output`, `-o` | Fichier de sortie (`.csv` ou `.json`) | (requis) |
| `--confidence`, `-c` | Confiance minimale 0..1 | `0.4` |
| `--sample-every`, `-s` | Détecter toutes les N frames (plus rapide) | `1` |
| `--quiet`, `-q` | Silencieux | |

### 2. Pousser les markers dans Resolve

Avant : ouvre ton projet DaVinci, importe la vidéo dans le Media Pool,
place-la sur le timeline, **sélectionne le clip**.

```powershell
# IMPORTANT : utiliser le Python embarqué de Resolve, PAS ton venv
& "C:\Program Files\Blackmagic Design\DaVinci Resolve\python.exe" `
    tools\people-detector\import_resolve.py `
    --csv output\mon_film.csv
```

Arguments :

| Flag | Description |
|---|---|
| `--csv` | Fichier CSV généré par `detect.py` (requis) |
| `--track` | Index de la piste vidéo (0 = V1) |
| `--confidence-format` | `decimal` / `percent` / `hide` |

## Fichier produit (CSV)

```csv
start_seconds,end_seconds,duration_seconds,avg_confidence
3.200,8.500,5.300,0.870
15.100,22.000,6.900,0.910
```

## Tips

- Au lancement, le détecteur affiche le provider utilisé :
  ```
  [detect] Using onnxruntime provider: DmlExecutionProvider   # ton iGPU AMD
  [detect] Using onnxruntime provider: CUDAExecutionProvider  # NVIDIA
  [detect] Using onnxruntime provider: CPUExecutionProvider   # fallback
  ```
  Si tu vois `CPUExecutionProvider` alors que tu as un GPU, installe
  `onnxruntime-directml` (déjà dans `requirements.txt`).
- Premier lancement : ~10 s supplémentaires pour exporter yolo11n → yolo11n.onnx.
  Le fichier `.onnx` est mis en cache dans le dossier courant. Relances suivantes : instantané.
- Pour une **preview rapide** sur une longue vidéo : `--sample-every 5` (~5× plus rapide).
- Le détecteur fonctionne avec **n'importe quel format vidéo** supporté par FFmpeg/OpenCV
  (.mp4, .mov, .mxf, .mkv...).
- Les markers sont créés en **bleu** sur toute la durée de présence (`duration_frames > 0`).

## Compatibilité GPU

Le détecteur utilise **ONNX Runtime** avec un provider auto-détecté. Ça couvre :

- ✅ **AMD iGPU RDNA 2/3** : Asus ROG Ally, ROG Ally X (Ryzen Z1 Extreme), Steam Deck APU,
  Ryzen 6000/7000/8000 series laptops — via `DmlExecutionProvider` (DirectML)
- ✅ **AMD Radeon dédié** RX 5000/6000/7000 — idem DirectML
- ✅ **Intel Arc** + iGPU Intel Xe — idem DirectML
- ✅ **NVIDIA** GeForce — via `CUDAExecutionProvider` si onnxruntime-gpu est aussi installé,
  sinon DirectML (un peu plus lent mais marche)
- ✅ CPU fallback (toujours disponible via `CPUExecutionProvider`)

> **Pourquoi pas `Ultralytics device="dml"` ?** Parce qu'Ultralytics passe par
> PyTorch `.to()` qui ne reconnaît pas `dml` comme device string (PyTorch est
> CUDA/MPS/XPU only). On exporte donc le modèle en **ONNX** au premier lancement,
> puis on l'infère via `onnxruntime` qui lui supporte DirectML nativement. Voilà
> pourquoi le message au démarrage dit `onnxruntime provider: …` et pas `device:`.

Aucune installation de drivers supplémentaires n'est nécessaire sur AMD/Intel :
le driver AMD Adrenalin ou Intel installé par Windows Update suffit.

## Limites connues

- Les changements de plans rapides (caméra qui coupe pendant qu'une personne parle)
  peuvent produire 2 markers très rapprochés — c'est normal, tu peux les fusionner à la main.
- YOLO ne distingue pas **qui** parle : si tu as 3 personnes à l'écran, le marker couvre
  toute la plage où l'une d'elles est visible.
