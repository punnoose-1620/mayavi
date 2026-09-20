# Hardware requirements

What a machine needs to run this repo on **Ubuntu** or **Windows**, **headless** or with a desktop. Numbers come from `models.py` (`checkRam`) and `gpu-check.py`, plus the Q4_K_M sizes in `models.json` / `README.md`. GPU names are NVIDIA’s published SKUs. Ryzen names are AMD CPU SKUs (AVX2). They are examples of each tier, not an exhaustive catalogue.

The runtime loads **one** GGUF at a time. It does not keep the committee in RAM together.

## How the factory decides

**RAM.** A load is allowed only if *free* RAM ≥ `file_size × 1.2 + 2 GB`. Installed RAM is not free RAM. Windows with a desktop and a browser often uses 3–5 GB before any GGUF. Ubuntu Server with no desktop is closer to 0.5–1 GB.

**GPU (`N_GPU_LAYERS=auto`).** Offload is only for **working agents**. The **router always stays on CPU**. `auto` requires `nvidia-smi`, a CUDA-capable `llama-cpp-python` wheel, and **dedicated** VRAM such that `dedicated − 1 GB` ≥ `file_size × 1.2`. Shared graphics (Intel UHD / Iris Xe, AMD Radeon 680M / 780M) do not count. AMD Radeon discrete cards are not on the `auto` path (no `nvidia-smi`); leave them as CPU unless you install a HIP wheel yourself and set `N_GPU_LAYERS`.

**CPU.** llama.cpp wants **x86_64 + AVX2** (Intel Haswell 2013+, all Ryzen 1000+). Older chips can run a no-AVX build; large runs will crawl.

**Python.** 3.11 or newer (`install.sh` / `install.ps1`).

## Model sets (disk and RAM)

| Set | Disk for GGUFs | Heaviest worker | File | Free RAM to pass `checkRam` | Dedicated NVIDIA VRAM for `auto` |
| --- | --- | --- | --- | --- | --- |
| Backup / laptop | ~7 GB | Qwen / Llama **3B** | ~2.0 GB | **~4.4 GB** | **4 GB** card (usable ~3 GB) |
| USB / committee | ~26 GB | Qwen / Llama **7B–8B** | ~4.7–4.9 GB | **~7.6–7.9 GB** | **8 GB** card |
| USB Gemma builder | (in the 26 GB) | Gemma 2 **9B** | ~5.8 GB | **~9.0 GB** | **12 GB** comfortable; 8 GB is tight |

Also budget ~1 GB for `.venv` and room under `outputs/` / `state/`. Practical free disk: **20 GB** (backup) or **32 GB** (USB set on a 32 GB stick plus a little OS space).

## Installed-RAM targets

| Target | Installed RAM | Set | Notes |
| --- | --- | --- | --- |
| Minimum old laptop | **8 GB** | Backup only | Headless Ubuntu is the realistic case. Windows desktop often fails the 3B `checkRam` with a browser open. Large runs are slow. |
| Comfortable laptop / desktop | **16 GB** | Backup; USB 7B if little else is open | Default for a machine you sit at. |
| USB committee including Gemma | **32 GB** | Full USB set | Needed if a desktop session shares the box. |

## NVIDIA GPUs (exact names)

`auto` uses dedicated VRAM only. Same-named laptop and desktop cards are **not** the same silicon; the VRAM column is what matters.

### Laptop

| Dedicated VRAM | Exact names | Offload |
| --- | --- | --- |
| 2 GB | GeForce **MX450**, **MX550** | CPU only |
| 4 GB | GeForce **RTX 2050**; **RTX 3050 Laptop GPU** (4 GB SKU); **RTX 3050 Ti Laptop GPU**; GeForce **GTX 1650** Laptop (4 GB) | Backup 3B possible; USB 7B stays CPU |
| 6 GB | **RTX 3050 Laptop GPU** (6 GB SKU); **RTX 3060 Laptop GPU**; **RTX 4050 Laptop GPU** | Backup 3B yes; USB 7B **no** under `auto` (usable 5 GB < ~5.6 GB) |
| 8 GB | **RTX 3070 / 3070 Ti Laptop GPU**; **RTX 3080 Laptop GPU** (8 GB SKU); **RTX 4060 Laptop GPU**; **RTX 4070 Laptop GPU** | USB 7B/8B yes; Gemma 2 9B tight |
| 12 GB | **RTX 4080 Laptop GPU** | Full USB set |
| 16 GB | **RTX 3080 Laptop GPU** (16 GB SKU); **RTX 3080 Ti Laptop GPU**; **RTX 4090 Laptop GPU** | Full USB set |

### Desktop

| Dedicated VRAM | Exact names | Offload |
| --- | --- | --- |
| 6 GB | GeForce **RTX 3050** (6 GB) | Backup 3B; not USB 7B |
| 8 GB | **RTX 3050** (8 GB); **RTX 3060** (8 GB SKU); **RTX 3060 Ti**; **RTX 3070**; **RTX 3070 Ti**; **RTX 4060**; **RTX 4060 Ti** (8 GB) | USB 7B/8B; Gemma 9B on the edge |
| 12 GB | **RTX 3060** (12 GB); **RTX 4070**; **RTX 4070 SUPER**; **RTX 4070 Ti** | Full USB set |
| 16 GB+ | **RTX 4060 Ti** (16 GB); **RTX 4070 Ti SUPER**; **RTX 4080** / **4080 SUPER**; **RTX 4090** | Full USB set with headroom |

A **GTX 1050** (2–4 GB) is not a useful offload target. Force CPU with `N_GPU_LAYERS=0` if the driver is present but VRAM is too small.

## Ryzen CPUs (exact names)

These are **CPU** examples. Their iGPUs (Vega, Radeon 660M / 680M / 780M) are ignored by `auto`. Pair any of them with a discrete NVIDIA card from the tables above if you want offload.

| Role | Exact CPU names | Cores / threads |
| --- | --- | --- |
| Thin / last-resort | Ryzen 5 **2500U**, **3500U** | 4 / 8 |
| Old-laptop minimum | Ryzen 5 **5500U**, **5600U**, **5625U**; Ryzen 5 **5500H** | 4–6 / 8–12 |
| Comfortable laptop | Ryzen 5 **5600H**, **6600H**, **7535HS**; Ryzen 7 **5800H**, **6800H**, **7735HS**, **7840HS** | 6–8 / 12–16 |
| Headless desktop / mini PC | Ryzen 5 **5600**, **7600**; Ryzen 7 **5700G**, **8700G** | 6–8 / 12–16 |

Intel equivalents for the same roles: **i5-8250U** (minimum 8 GB laptop), **i5-1135G7** / **i5-1240P** (comfortable), **i5-12400** / **i5-13400** (desktop). Avoid **Ryzen 3 7320U** and **Athlon 3000G** except for stub/`--no-model` checks.

AMD discrete cards (**Radeon RX 6600** 8 GB, **RX 7600** 8 GB, **RX 6800** 16 GB) can run llama.cpp via HIP in other setups. This repo’s default wheel is CPU-only.

## Ubuntu vs Windows

| | Ubuntu 22.04 / 24.04 LTS | Windows 10 (22H2+) / 11 |
| --- | --- | --- |
| Install | `./install.sh` | `.\install.ps1` |
| Python | `python3.11` + `python3.11-venv` | Python 3.11+ from python.org (not the Store stub if you can avoid it) |
| Start UI | `./.venv/bin/python app.py --port 9001` | `run-id10t.bat` or `.venv\Scripts\python.exe app.py --port 9001` |
| GPU | NVIDIA driver + `nvidia-smi` + CUDA wheel | Same; GeForce Game Ready or Studio driver |
| Headless | First-class: no display needed | Possible (RDP/SSH) but the desktop session still costs RAM |

The chat UI binds **127.0.0.1** only. Another PC on the LAN cannot open the Ubuntu box’s port. Use an SSH tunnel:

```bash
ssh -L 9001:127.0.0.1:9001 user@ubuntu-host
```

then open `http://127.0.0.1:9001/` on the client. There is no login on `/turns`. Do not bind `0.0.0.0` until that exists.

Mail/calendar OAuth opens a **local browser** on the machine that runs connect. On a headless box, finish Allow once on a desktop and copy `state/tokens/`, or skip mail.

## Headless vs regular

### Headless (Ubuntu Server, no desktop)

- Lowest RAM tax. Best chance for an **8 GB** laptop on the **backup** set.
- Start `app.py` under systemd or a `tmux`/`screen` session. Access via SSH tunnel from your daily laptop.
- No `run-id10t.bat`. Do not expect a local browser.
- Large coding runs are sequential and can take a long time on 4–6 cores. That is the intended shape (overnight), not a defect.
- Close other services. Swap will keep the process alive but tokens/s fall off a cliff.

### Regular (Ubuntu Desktop or Windows)

- Budget **16 GB** if you will keep a browser and the UI open.
- The UI and Google/Microsoft Allow need a display (or an RDP session).
- On Windows, treat free RAM as the scarce number: Task Manager → Performance → Memory → available, not “installed.”

## Suggested builds

**Minimum — old laptop, Ubuntu headless, backup set**

- CPU: Ryzen 5 **5500U** or Intel **i5-8250U**
- RAM: 8 GB
- GPU: none (iGPU ignored)
- Disk: 20 GB free
- Access: SSH tunnel to `app.py` on port 9001

**Typical — current laptop, Ubuntu or Windows desktop, backup set**

- CPU: Ryzen 5 **5600H** / **7535HS** or Intel **i5-1240P**
- RAM: 16 GB
- GPU: optional **RTX 3050 Laptop GPU** (4 GB or 6 GB) for 3B offload
- Disk: 20 GB free

**USB committee — desktop**

- CPU: Ryzen 5 **5600** / **7600** or Intel **i5-12400**
- RAM: 32 GB (16 GB only if the box is otherwise idle)
- GPU: **RTX 4060** (8 GB) or **RTX 3060** (12 GB). Use the 12 GB card if you want Gemma 2 9B offloaded.
- Disk: 32 GB free (or the USB stick as `MODELS_DIR`)

`--no-model` and `pytest` do not load GGUFs. Use those to prove the install before you copy weights.
