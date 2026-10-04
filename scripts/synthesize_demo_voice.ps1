param(
    [Parameter(Mandatory = $true)]
    [string]$Storyboard,

    [Parameter(Mandatory = $true)]
    [ValidateSet("product_demo", "technical_walkthrough")]
    [string]$Video,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [ValidateSet(0, 1)]
    [int]$Rate = 1,

    [string]$VoiceName
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Storyboard -PathType Leaf)) {
    throw "Storyboard file not found: $Storyboard"
}

$story = Get-Content -LiteralPath $Storyboard -Raw -Encoding UTF8 | ConvertFrom-Json
$videoProperty = $story.videos.PSObject.Properties[$Video]
if ($null -eq $videoProperty -or $null -eq $videoProperty.Value) {
    throw "Storyboard has no videos.$Video entry."
}

if ([string]::IsNullOrWhiteSpace($VoiceName)) {
    $VoiceName = [string]$story.voice
}
if ([string]::IsNullOrWhiteSpace($VoiceName)) {
    $VoiceName = "Microsoft Zira Desktop"
}

$scenes = @($videoProperty.Value.scenes)
if ($scenes.Count -ne 6) {
    throw "Expected six scenes for $Video; found $($scenes.Count)."
}
foreach ($scene in $scenes) {
    if ([string]::IsNullOrWhiteSpace([string]$scene.id) -or [string]::IsNullOrWhiteSpace([string]$scene.narration)) {
        throw "Every scene needs a non-empty id and narration."
    }
}

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $installed = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name })
    if ($installed -notcontains $VoiceName) {
        $available = if ($installed.Count -gt 0) { $installed -join ", " } else { "(none)" }
        throw "Required local SAPI voice '$VoiceName' is unavailable. Installed voices: $available"
    }
    $synth.SelectVoice($VoiceName)
    $synth.Rate = $Rate
    $synth.Volume = 100

    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    foreach ($scene in $scenes) {
        $safeId = [regex]::Replace([string]$scene.id, "[^A-Za-z0-9_.-]+", "_")
        $wavPath = Join-Path $OutputDir ("{0}_{1}.wav" -f $Video, $safeId)
        $synth.SetOutputToWaveFile($wavPath)
        try {
            $synth.Speak([string]$scene.narration)
            $synth.SetOutputToNull()
        }
        catch {
            $synth.SetOutputToNull()
            if (Test-Path -LiteralPath $wavPath) {
                Remove-Item -LiteralPath $wavPath -Force
            }
            throw
        }
        Write-Output $wavPath
    }
}
finally {
    $synth.Dispose()
}
