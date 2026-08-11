#!/usr/bin/env python3
"""Synthetic incident generator for Sirens.

Produces a folder of fabricated C-IED incident reports plus a ground-truth key,
so the linker can be measured (precision/recall) against known answers.

Everything here is FABRICATED and descriptive. Reports describe what was
observed and reported in the field (initiation, emplacement, container, TTP,
and the observable object: type, colour, condition, fuze-visible). No technical
performance, fill, fuzing-behaviour or handling information is generated — the
tool links reports, it is not a munitions reference.

Usage:
    python generate_incidents.py --n 100 --out data/generated --seed 7
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random

# --- Real South Lebanon place names (public geography) ----------------------
SOUTH_LB_PLACES = [
    "Bint Jbeil", "Aïn Ebel", "Rmeish", "Marjayoun", "Khiam", "Nabatieh",
    "Tibnin", "Yaroun", "Kfar Kila", "Maroun al-Ras", "Aitaroun", "Blida",
    "Houla", "Meiss ej-Jabal", "Qana", "Tayr Harfa", "Naqoura", "Chaqra",
    "Kfar Tibnit", "Deir Mimas", "Ghandouriyeh", "Srifa", "Zawtar", "Kfar Roummane",
]
ROUTES = ["the Nabatieh–Marjayoun road", "the coastal road near Naqoura",
          "the Bint Jbeil approach", "the Khiam bypass", "the wadi track east of Houla",
          "the ridge road above Aïn Ebel"]

# --- Surface phrasings that map to canonical taxonomy values ----------------
# Each list gives DIFFERENT ways a report might phrase the same canonical value,
# so the extractor's normalization gets a real workout (messy wording).
SURF = {
    "initiation": {
        "victim_operated": ["victim-operated", "victim operated", "pressure-initiated", "VOIED"],
        "command_initiated": ["command-initiated", "command detonated", "command wire initiated"],
        "remote_controlled": ["remote-controlled", "RCIED", "radio-controlled"],
        "time_delay": ["time-delay", "timer-initiated", "delayed initiation"],
    },
    "trigger": {
        "pressure_plate": ["pressure plate", "pressure-plate", "PP switch", "plank switch"],
        "command_wire": ["command wire", "hard wire", "trigger wire", "CW"],
        "passive_infrared": ["passive infrared", "PIR sensor", "IR trigger"],
        "radio_control": ["radio control", "long-range cordless", "RC trigger"],
        "victim_tripwire": ["tripwire", "trip-wire", "pull switch"],
    },
    "emplacement": {
        "buried_roadside": ["buried at the road verge", "dug-in roadside", "buried on the shoulder"],
        "culvert": ["in a culvert", "under the road drainage", "under the bridge"],
        "vehicle_borne": ["vehicle-borne", "VBIED", "car bomb"],
        "thrown_placed": ["hand-emplaced", "left in place", "placed device"],
        "concealed_object": ["concealed in roadside debris", "hidden in a wall cavity", "disguised as rubbish"],
    },
    "container": {
        "pressure_cooker": ["pressure cooker", "cooker device"],
        "plastic_jug": ["plastic jug", "jerry can", "yellow jug"],
        "metal_drum": ["metal drum", "oil barrel", "metal barrel"],
        "vehicle_body": ["vehicle wheel well", "under the seat", "boot of the car"],
        "packaging": ["cardboard box", "rice bag", "flour sack"],
    },
    "charge_label": {
        "hme_label": ["homemade explosive", "HME", "improvised mixture"],
        "repurposed_ordnance": ["repurposed artillery shell", "a mortar round used as the charge", "UXO repurposed"],
        "commercial_label": ["commercial explosive", "mining explosive"],
    },
    "ttp": {
        "secondary_device": ["a secondary device", "a follow-up device for responders", "a come-on device"],
        "complex_ambush": ["a complex ambush with small-arms fire", "a combined attack", "small-arms and IED"],
        "daisy_chain": ["daisy-chained charges", "multiple linked charges"],
        "false_surrender": ["a come-on lure", "a baited approach"],
        "target_civilian": ["a crowded market", "civilians nearby", "near worshippers"],
        "target_convoy": ["a convoy", "a resupply patrol", "a logistics route"],
    },
    "object_type": {
        "rocket_107mm": ["107mm rocket", "107 mm rocket", "Type-63 rocket"],
        "rocket_122mm": ["122mm rocket", "Grad-type rocket"],
        "rocket_generic": ["rocket", "rocket-propelled round"],
        "mortar_round": ["mortar round", "60mm mortar", "82mm mortar bomb"],
        "artillery_shell": ["artillery shell", "155mm projectile", "howitzer round"],
        "projectile_generic": ["projectile", "shell"],
        "grenade": ["hand grenade", "rifle grenade"],
        "landmine": ["anti-personnel mine", "anti-tank mine"],
        "submunition": ["submunition", "cluster bomblet", "dud submunition"],
        "uxo_generic": ["UXO", "unexploded ordnance", "abandoned ordnance"],
    },
    "colour": {
        "green": ["olive green", "olive drab", "dark green"],
        "tan": ["sand-coloured", "desert tan", "khaki"],
        "black": ["black"], "grey": ["metallic grey"], "rust": ["rust-coloured", "heavily rusted"],
        "yellow": ["with a yellow band"], "red": ["with a red band"], "blue": ["blue"], "white": ["off-white"],
    },
    "shape": {
        "fin_stabilised": ["fin-stabilised", "finned", "with tail fins"],
        "cylindrical": ["cylindrical", "tubular"],
        "conical_nose": ["with a conical nose", "with a pointed nose"],
        "spherical": ["ball-shaped"], "boxed": ["box-shaped"], "warhead": ["with a bulbous warhead"],
    },
    "condition": {
        "intact": ["intact", "undamaged"],
        "corroded": ["corroded", "weathered", "heavily rusted"],
        "leaking": ["leaking", "weeping from a seam"],
        "damaged": ["damaged", "with a cracked casing"],
        "partially_buried": ["partially buried", "half-buried", "protruding from the ground"],
    },
    "fuze": {
        "fuze_fitted": ["a nose fuze fitted", "fuze visible", "fuzed"],
        "no_fuze_visible": ["no visible fuze", "fuze absent"],
        "impact_fuze": ["a point-detonating fuze"],
        "time_fuze": ["a mechanical time fuze"],
    },
}

SIZES = ["approximately 1 m long", "roughly 80 cm", "about 60cm", "small",
         "medium", "large-calibre", ""]

FIRST = ["Rida", "Kamal", "Hassan", "Ali", "Nabil", "Samir", "Jad", "Fadi", "Marwan", "Ziad"]
LAST = ["Karim", "Dagher", "Nasr", "Haidar", "Fares", "Aoun", "Khalil", "Saad", "Younes", "Chami"]
GROUP_WORDS = ["Cell", "Network", "Group", "Faction"]
GROUP_NAMES = ["Litani", "Ridge", "Border", "Wadi", "Cedar", "Southern"]


def phr(rng, facet, value):
    return rng.choice(SURF[facet][value])


def make_signature(rng):
    """A network's fixed profile: the features its incidents tend to share."""
    return {
        "initiation": rng.choice(list(SURF["initiation"])),
        "trigger": rng.choice(list(SURF["trigger"])),
        "emplacement": rng.choice(list(SURF["emplacement"])),
        "container": rng.choice(list(SURF["container"])),
        "charge_label": rng.choice(list(SURF["charge_label"])),
        "ttp": rng.choice(list(SURF["ttp"])),
        "area": rng.sample(SOUTH_LB_PLACES, k=rng.randint(2, 4)),
        "group": f"the {rng.choice(GROUP_NAMES)} {rng.choice(GROUP_WORDS)}",
        "person": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
        "phone": f"0{rng.randint(70,81)}-{rng.randint(100,999)}-{rng.randint(1000,9999)}",
        # Some networks also leave a characteristic object.
        "object_type": rng.choice(list(SURF["object_type"])),
        "colour": rng.choice(list(SURF["colour"])),
    }


def build_report(rng, sig, idx, noisy=False):
    """Compose a messy free-text report from a signature, dropping/altering
    fields to simulate real reporting variance."""
    place = rng.choice(sig["area"])
    parts = []
    date = f"2026-{rng.randint(1,6):02d}-{rng.randint(1,28):02d}"

    # Opening: what happened, where.
    verb = rng.choice(["functioned against", "was emplaced against", "targeted",
                       "was located near", "struck"])
    tgt = phr(rng, "ttp", sig["ttp"]) if rng.random() > 0.3 else "a patrol"
    parts.append(f"On {date[8:]}{rng.choice(['', ' MAR', ' APR', ''])} an IED {verb} {tgt} near {place}.")

    # Device details — each included with some probability (missing fields).
    if rng.random() > 0.15:
        parts.append(f"Assessed as {phr(rng,'initiation',sig['initiation'])}.")
    if rng.random() > 0.2:
        parts.append(f"Post-blast indicators: a {phr(rng,'trigger',sig['trigger'])}"
                     + (f" and a {phr(rng,'container',sig['container'])}" if rng.random()>0.4 else "") + ".")
    if rng.random() > 0.35:
        parts.append(f"Emplacement {phr(rng,'emplacement',sig['emplacement'])}.")
    if rng.random() > 0.4:
        parts.append(f"Main charge {phr(rng,'charge_label',sig['charge_label'])}.")

    # Sometimes an observed object with descriptors.
    if rng.random() > 0.5:
        obj = phr(rng, "object_type", sig["object_type"])
        desc = [phr(rng, "colour", sig["colour"])]
        if rng.random() > 0.5: desc.append(phr(rng, "shape", rng.choice(list(SURF["shape"]))))
        if rng.random() > 0.5: desc.append(phr(rng, "condition", rng.choice(list(SURF["condition"]))))
        if rng.random() > 0.5: desc.append(phr(rng, "fuze", rng.choice(list(SURF["fuze"]))))
        size = rng.choice(SIZES)
        d = ", ".join([x for x in desc if x])
        parts.append(f"A recovered item: a {obj}"
                     + (f", {size}" if size else "")
                     + (f", {d}" if d else "") + ".")
        if rng.random() > 0.6:
            parts.append(f"Photo: img_{idx:03d}.jpg.")

    # Identity signals — the strong links, included probabilistically.
    if rng.random() > 0.45:
        parts.append(f"Source reporting references {sig['group']}"
                     + (f" and an individual, {sig['person']}" if rng.random()>0.5 else "") + ".")
    if rng.random() > 0.7:
        parts.append(f"A contact number {sig['phone']} was recovered.")

    rng.shuffle_hint = None
    text = " ".join(parts)

    # Messy: occasional truncation (partial report).
    if noisy and rng.random() > 0.8:
        text = text[: int(len(text) * rng.uniform(0.4, 0.7))].rstrip() + " …"

    rec = {"id": f"INC-{idx:03d}", "date": date, "location": place, "narrative": text}
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--networks", type=int, default=5)
    ap.add_argument("--noise-frac", type=float, default=0.2,
                    help="fraction of incidents that belong to NO network (singletons)")
    ap.add_argument("--out", default="data/generated")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    signatures = [make_signature(rng) for _ in range(args.networks)]

    incidents, key = [], {}
    n_noise = int(args.n * args.noise_frac)
    n_net = args.n - n_noise

    idx = 1
    # Networked incidents: assign each to a network, size networks unevenly.
    weights = [rng.randint(2, 6) for _ in range(args.networks)]
    assignments = rng.choices(range(args.networks), weights=weights, k=n_net)
    for net in assignments:
        rec = build_report(rng, signatures[net], idx, noisy=True)
        rec_id = rec["id"]
        key[rec_id] = f"NET-{net+1:02d}"
        incidents.append(rec); idx += 1

    # Noise incidents: each gets its OWN random one-off signature (unlinked).
    for _ in range(n_noise):
        lone = make_signature(rng)
        rec = build_report(rng, lone, idx, noisy=True)
        key[rec["id"]] = "NOISE"
        incidents.append(rec); idx += 1

    rng.shuffle(incidents)

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "incidents.json").write_text(json.dumps(incidents, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
    (out / "ground_truth.json").write_text(json.dumps(key, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
    n_clusters = len({v for v in key.values() if v != "NOISE"})
    print(f"[+] wrote {len(incidents)} incidents -> {out/'incidents.json'}")
    print(f"[+] ground truth ({n_clusters} networks, {list(key.values()).count('NOISE')} noise) "
          f"-> {out/'ground_truth.json'}")


if __name__ == "__main__":
    main()
