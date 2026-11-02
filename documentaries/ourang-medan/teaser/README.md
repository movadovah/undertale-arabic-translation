# Ourang Medan: cold-open teaser

A ~2.5-minute (150 s) rendering of the documentary's cold open, made entirely in code: vector-style motion graphics, synthesized sound design and Morse code, and Arabic captions. **There is no voice-over.** Record one and lay it over the captions.

## Timeline
| Time | Scene |
|---|---|
| 0:00–0:09 | Black screen, red SOS pulses with Morse audio, snap-zoom into the sea |
| 0:09–0:60 | The strait at night: fog, lightning, the ship drifting, an "S . O . S" slam, a garbled signal |
| 1:00–1:14 | Oscilloscope: "I DIE" decoded, then the Arabic "أنا… أموت", then dead air |
| 1:14–1:32 | Montage: صمت / موت / زمجرة / برد / دخان / نار / اختفاء |
| 1:32–1:58 | Fire, then the ship sinks |
| 1:58–2:30 | Morse dots form the title: «سفينة الأشباح في المضيق», then «الأسطورة / السجلّ» |

## Rebuild
Requirements: Python 3 with Pillow (built with libraqm, for Arabic shaping) and numpy, plus ffmpeg.
Fonts (OFL): Noto Kufi Arabic and Amiri. Put `NotoKufi.ttf` and `Amiri-1.000/Amiri-Regular.ttf` in a fonts folder.

```bash
python3 render.py <fonts_dir> <out_dir>               # full video -> <out_dir>/ourang-medan-teaser.mp4
python3 render.py <fonts_dir> <out_dir> 12 62 110     # preview stills at those seconds
```
