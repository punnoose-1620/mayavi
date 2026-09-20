# Server hardware (cart)

Home headless box for this repo: Ubuntu Server, loopback UI, SSH from the LAN, one user. See [`Hardware Requirements.md`](Hardware%20Requirements.md) for the floors this list was chosen against.

**Buy now** is the compute and storage cart. **Buy later** is PSU, cooling upgrades, and the enclosure.

## Buy now

| Role | Choice | Notes |
| --- | --- | --- |
| CPU | **AMD Ryzen 5 7600** | 6c/12t, 65 W TDP, ~88 W PPT, AVX2, AM5. Stock Wraith Stealth is enough until a cooling upgrade. |
| Board | **ASUS B650** (AM5) | Confirm one **CPU 8-pin (4+4)** and enough SATA/M.2. BIOS flashback if the kit RAM is picky. |
| RAM | **2×16 GB DDR5** (32 GB) | Dual channel. EXPO profile optional; leave default if the box is unstable at EXPO. |
| GPU | **GeForce RTX 5060 Ti 16 GB** | 180 W TGP, 16 GB GDDR7. Official 5060 is 8 GB only — the box must say **5060 Ti**. Most cards want **one 8-pin**; some AIB models use 12V-2x6 + adapter. |
| Boot / models | **1 TB NVMe SSD** | OS, `.venv`, GGUFs, `state/`. |
| Bulk disk | **8 TB HDD** | `input/` and `outputs/`. Add more SATA disks later without changing the PSU class. |

Not in this cart: case fans beyond what the enclosure needs, a monitor, Windows.

## Buy later — power supply

Target: **650 W 80+ Gold**, name brand, **5–10 year** warranty. NVIDIA/board-partner floor for a 5060 Ti is **600 W**; 650 W leaves room for a second HDD. Do not buy 450–500 W or a no-name “650 W”.

Sustained draw for this repo (one GGUF on the GPU): about **250–320 W** at the wall. Brief peaks (GPU + HDD spin-up + CPU boost) stay under **~400 W**.

**Look for**

- Seasonic Focus / Prime, Corsair RMx / RM, be quiet! Straight Power / Pure Power 12, Super Flower Leadex, MSI MAG A-GL, Fractal Ion+
- **80+ Gold** (Platinum is optional)
- **ATX 3.0 / 3.1** if the exact Ti card uses 12V-2x6; otherwise a good ATX 2.x Gold with a **single PCIe 8-pin** is enough
- Cables: **24-pin**, **CPU 8-pin (4+4)**, **one PCIe 8-pin** (or native 12V-2x6), **SATA** for the 8 TB
- One cable per GPU connector. Native SATA, not Molex adapters
- Fully or semi-modular

A **600–800 VA UPS** is more useful than an 850 W PSU if the HDD holds documents.

## Buy later — cooling

**Now:** stock Ryzen cooler + the GPU’s own fans. Headless, one model at a time, this is enough if the enclosure has intake and exhaust.

**Later, if budget allows (pick one path, not both at first)**

| Path | When it makes sense | Constraints |
| --- | --- | --- |
| **AIO liquid (240/280 mm)** | Quieter CPU, warmer room, or a sealed wood/steel top with poor chimney flow | Need radiator + two fans vented **out** of the enclosure. Do not bury an AIO in a closed box. |
| **Mineral-oil submersion** | Showpiece / full discretion, no case fans | Custom tank, oil-safe parts, no paper/cardboard GPU pads, PSU and HDD usually **outside** the bath (PSU is open-frame or external; spinning HDD + oil is a bad mix). Plan this as a rebuild, not a drop-in. |

Air first. Decide liquid vs oil after the box has run a few large committees and you know the noise/heat.

## Buy later — enclosure

Custom **wood and stainless** tabletop, discreet, not a gamer tower.

- Keep **intake low, exhaust high** (or a rear slot). A sealed plinth will cook the 180 W GPU.
- Dust filter on intake. Wood is fine; do not block the GPU’s open end.
- PSU: floor of the box, fan down into a vent, or fan up if the floor is closed.
- HDD: vibration isolation (rubber grommets) so the tabletop does not hum.
- If oil-submerged later: tank is a separate object; wood lid is cosmetic, steel is the structure.
- I/O: one LAN, one USB for keyboard if needed, power button. No display.

## Table build notes

Low wood/steel plinth. L-cables / riser to keep height down. AIO later so there is no CPU tower.

- **Stack:** floor intake → cavity → exhaust high. Table on feet, not flush on carpet. Filters on the floor holes. Wash them.
- **AIO:** vertical at one **end**. Pull from below, dump out the **top or rear apron** of that end. Top of the rad = highest point in the loop. Tubes low. Do not vent under a laptop.
- **GPU:** fan-**down**, card on end (PCIe 4.0 riser). Wooden channels on both **long ends** turn fin exhaust **up**. I/O end is the clean chimney; power end goes **around** the 8-pin, no pinch. Thick short 90° GPU cable.
- **GPU intake:** third path — floor hole gasketed to the **fan rings**. If that is open to the cavity, the card recirculates.
- **Backplate** faces the lid. Leave a gap. Do not screw wood onto the card.
- **One shared chimney** for GPU + rad is fine. Size floor and top openings for **both** (~260 W), not the AIO alone.
- **PSU** has its own floor vent. **HDD** rubber-mounted, away from the rad wall.
- Wood can sit near 80–90 °C air; keep a few mm off hot metal. Smooth or line the channels.
- Air + AIO first. Oil bath is a later rebuild (PSU and HDD stay out of the oil).

## Software target (not a purchase)

- Ubuntu Server 24.04, `./install.sh`, `app.py --port 9001`
- Access from the daily laptop: `ssh -L 9001:127.0.0.1:9001 user@this-box`
- `N_GPU_LAYERS=auto` after the NVIDIA driver and a CUDA `llama-cpp-python` wheel
- Models on the SSD; documents on the 8 TB
