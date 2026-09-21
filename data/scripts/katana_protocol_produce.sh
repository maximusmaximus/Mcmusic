#!/bin/bash
# Produce KATANA-PROTOCOL — 5-track VØIDRIDE album
python3 /opt/data/skills/master-producer/master-producer/scripts/produce-album.py \
  --brief "Album: KATANA-PROTOCOL
Genre: drift phonk / industrial trap
BPM range: 140-155
Key: Fm
Visual: A cybernetic ronin unsheathing a glowing plasma katana in an ink-black rain-slicked alleyway

Track titles and briefs:
1. MONOMOLECULAR EDGE — Aggressive opener with razor-sharp synth lead, metallic scrape samples, pounding 808s. Drift phonk/industrial trap fusion.
2. BLOOD SHEATH — Darker, more atmospheric. Cold pads, distorted 808 cowbells, slicing transients. Mid-tempo tension builder.
3. IAIDO DRIFT — High-velocity. Fast hi-hat rolls, sub-bass impacts, sword draw samples as rhythmic elements. Maximum energy.
4. CARBON SCABBARD — Industrial percussion focus. Metallic clang sounds, cyber-noir ambiance, linear groove with explosive drops.
5. SHADOW SEVER — Closer. Lethal intensity throughout, razor-sharp synth leads, cold atmospheric pads, high-speed nocturnal feel.

Production brief: Aggressive drift phonk fused with razor-sharp industrial percussion and distorted 808 cowbells. Metallic sword scrape samples, slicing transients, sub-bass impacts, cold atmospheric pads. High-velocity energy built for high-speed nocturnal pursuits, razor-sharp synth leads, lethal cyber-noir ambiance." \
  --tracks 5 \
  --duration 260 \
  --quality standard
