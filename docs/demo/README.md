# NOVA-MAT submission videos

NOVA-MAT turns material-screening evidence into the next scientific decision.
These English clips present the completed `native-adaptive-live-09` loop:
the agents review an actual Result, choose a follow-up, execute a registered
experiment, complete controlled validation and export traceable evidence.
Team introduction is handled separately by the team.

For the current submission, pair B's Product demo with the revised Technical
walkthrough below, which matches its visual style:

| Submission field | Local file | Duration | Size |
|---|---|---:|---:|
| **Technical walkthrough — revised** | `D:\Workspace\HackOS\.verification-repro\demo-videos-bstyle\technical_walkthrough_bstyle.mp4` | **57.97 seconds** | **about 2.31 MB** |

The original A clips are retained for reference:

| Submission field | Local file | Duration | Size |
|---|---|---:|---:|
| Product demo — original A version | `D:\Workspace\HackOS\.verification-repro\demo-videos\product_demo.mp4` | 55.00 seconds | about 2.36 MB |
| Technical walkthrough — original A version | `D:\Workspace\HackOS\.verification-repro\demo-videos\technical_walkthrough.mp4` | 57.97 seconds | about 2.67 MB |

All A-rendered clips are 1920x1080, 30 fps, MP4 H.264/yuv420p with AAC audio.
Each is under the submission form's 60-second and 1-GB limits. Use the revised
MP4 for Technical walkthrough. The platform screenshot indicates that selecting
a file alone
does not upload it: upload happens on Save draft or Submit project. This stage
does not claim an upload or final submission.

The original A design uses a navy/teal/blue palette, a large NOVA-MAT opening title,
an abstract lattice representing the scientific workflow, pulsing decision
paths and animated evidence chains. Figures retain their exact values while
cards and paths animate. The spoken pitch focuses on result-informed decisions,
controlled validation and traceable scientific output.

The original A Product demo shows the frozen question, real primary counts, three offered
follow-up choices, the selected threshold analysis, one completed frozen
holdout and the exported evidence. The Technical walkthrough explains A/B
ownership, shared Spec/Result contracts, result-informed planning, provenance
and the separate controlled holdout gate.

The controlled holdout retains the observed direction and quantifies
uncertainty under the frozen rules. The original A Product demo displays its
recorded classification and resampling interval, while the presentation focuses on the
completed engineering loop and the evidence it produces. See
[A's scientific acceptance](../results/native09_science_acceptance/README.md).

## Technical walkthrough matched to B's Product demo

The revised technical clip follows the team-provided Product demo's visual
direction: a dark navy background, Georgia serif headlines with cyan emphasis,
left-side explanations, right-side architecture diagrams, a recorded-evidence
badge and a continuous chapter progress line. It reuses the six original English
narration WAVs and provides a separate SRT file to keep the diagrams uncluttered.

Its six chapters explain the scientific/orchestration boundary, the native agent
roles and selected threshold follow-up, registered Spec/Result links, host-owned
holdout controls and evidence export. Actual shortened IDs and hashes come from
the existing public native09 records. The team-supplied Product video is a style
reference only; its bytes and the original A videos remain unchanged.

[technical_bstyle.json](technical_bstyle.json) pins the public evidence and
original narration. [technical_bstyle_validation.json](technical_bstyle_validation.json)
records verification of the delivered variant. Reproduce it using the original
audio directory and existing local media tools:

```powershell
& 'D:/Dev/Python314/python.exe' scripts/render_technical_walkthrough_bstyle.py `
    --storyboard docs/demo/technical_bstyle.json `
    --audio-dir .verification-repro/demo-videos/audio `
    --output-dir .verification-repro/demo-videos-bstyle `
    --ffmpeg .verification-repro/video-tools/ffmpeg-win-x86_64-v7.1.exe
```

Add `--preview-only` to produce the six scene previews without encoding the MP4.
The style-reference video is retained locally under `.verification-repro` and
is not included in Git. No new scientific, model or holdout execution is used
to produce this variant.

## Delivery verification

[validation.json](validation.json) records actual full audio/video decode exits,
container durations, file hashes, subtitle/narration equality and unchanged
native09 source hashes. Final scene previews were visually inspected, including
the actual discovery counts and the holdout interval crossing zero.
[evidence.json](evidence.json) binds the displayed scientific values to existing
public Results/payloads; [storyboard.json](storyboard.json) contains the scenes
and English narration.

MP4s, WAVs, encoder, temporary scene images and per-render manifests stay in the
ignored local `.verification-repro` directory. Git contains the small recipes,
source references and validation records. No raw/prepared data, private model
response, credentials, live context or running SQLite is included.

## Reproduce locally

Use the existing Windows Python with Pillow/NumPy, Windows System.Speech voice
`Microsoft Zira Desktop`, and a local FFmpeg executable. This media workflow does
not change the scientific environment or frozen dependency files. Run these
from the repository root in PowerShell:

```powershell
foreach ($video in @('product_demo', 'technical_walkthrough')) {
    & .\scripts\synthesize_demo_voice.ps1 `
        -Storyboard docs/demo/storyboard.json -Video $video `
        -OutputDir .verification-repro/demo-videos/audio -Rate 1
    & 'D:/Dev/Python314/python.exe' scripts/render_submission_video.py `
        --storyboard docs/demo/storyboard.json --video $video `
        --output-dir .verification-repro/demo-videos `
        --audio-dir .verification-repro/demo-videos/audio `
        --ffmpeg .verification-repro/video-tools/ffmpeg-win-x86_64-v7.1.exe
}
```

Preview-only mode needs no encoder or voice files:

```powershell
& 'D:/Dev/Python314/python.exe' scripts/render_submission_video.py `
    --storyboard docs/demo/storyboard.json --video product_demo `
    --output-dir .verification-repro/demo-videos --preview-only
```

The renderer rejects narration that cannot fit its 59-second cap, preserves
scientific values throughout animations and performs no model/science calls.
Voice/font/encoder differences can change a regenerated file's bytes; the
published validation hashes identify the actual delivered local clips.

## Evidence notes

The videos are designed replays of existing real-run evidence, rather than a
new live execution or browser recording. The initial hypothesis/baseline are
host-seeded. Method comparison was offered but not executed in native09. The
holdout classification is `direction_consistent_inconclusive`, with its primary
interval crossing zero. The presentation makes no new-material, measured
physical-performance, acceleration or cost-comparison claim.
