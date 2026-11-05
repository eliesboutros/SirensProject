"""Outline icons for the home page actions and the munition families.

Plain silhouettes drawn for Sirens (no photos, no third-party artwork): one
48x48 stroke drawing per family, in the page's text colour. They show only
the general outline a member of the public would recognise, never internal
parts.
"""
from __future__ import annotations

from markupsafe import Markup

_WRAP = ('<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2" '
         'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{}</svg>')

_PATHS = {
    # --- munition families (side views, nose to the right)
    "mortar": '<path d="M16 24c0-4.5 5.5-7.5 12-7.5 6 0 11 3.5 13 7.5-2 4-7 7.5-13 7.5-6.5 0-12-3-12-7.5z"/>'
              '<path d="M16 22.5H10v3h6"/><path d="M5 17l5 5.5M5 31l5-5.5M7 24h3"/><path d="M22 17.3v13.4"/>',
    "rocket": '<path d="M9 20.5h26l7 3.5-7 3.5H9z"/><path d="M9 20.5L5 15h6l4 5.5M9 27.5L5 33h6l4-5.5"/>'
              '<path d="M17 20.5v7"/>',
    "artillery": '<path d="M9 16.5h19c7 0 12.5 3.5 14.5 7.5-2 4-7.5 7.5-14.5 7.5H9z"/>'
                 '<path d="M14 16.5v15M17 16.5v15"/>',
    "grenade": '<circle cx="22" cy="29" r="11"/><path d="M18 18v-4h8v4"/><path d="M26 15.5c5 0 8.5 3 8.5 8"/>'
               '<circle cx="15" cy="12" r="3"/><path d="M17.5 13.5L19 15"/>',
    "mine": '<path d="M6 27c0-3.3 8-6 18-6s18 2.7 18 6-8 6-18 6-18-2.7-18-6z"/>'
            '<path d="M6 27v4c0 3.3 8 6 18 6s18-2.7 18-6v-4"/><path d="M20 21.5V17h8v4.5"/>',
    "cluster": '<circle cx="15" cy="17" r="6"/><circle cx="33" cy="17" r="6"/><circle cx="24" cy="32" r="6"/>'
               '<path d="M15 11v-3M33 11v-3M24 26v-2"/>',
    "bomb": '<path d="M12 24c0-5.5 8-9 17-9 7 0 11.5 4.5 13.5 9-2 4.5-6.5 9-13.5 9-9 0-17-3.5-17-9z"/>'
            '<path d="M12 21H5v6h7M5 17.5v13"/>',
    "missile": '<path d="M5 22h31l8 2-8 2H5z"/><path d="M19 22l-4-7h5l5 7M19 26l-4 7h5l5-7"/>'
               '<path d="M5 22l-1-4h4l2 4M5 26l-1 4h4l2-4"/>',
    "drone": '<path d="M24 6l17 32-17-6.5L7 38z"/><path d="M24 6v25.5"/>',
    "ied": '<rect x="7" y="20" width="21" height="16" rx="2.5"/><path d="M12 26h11M12 30h7"/>'
           '<path d="M28 25c6 0 6-11 12-11"/><circle cx="41" cy="13" r="2"/>',
    "other": '<circle cx="24" cy="24" r="17"/><path d="M19 19.5c0-3 2.3-5 5-5s5 2 5 4.8c0 3.7-5 4.2-5 8.2"/>'
             '<path d="M24 33v.1"/>',
    "vbied": '<path d="M5 30v-6l5-1 5-7h16l6 7 6 1v6z"/><circle cx="14" cy="31" r="4"/><circle cx="35" cy="31" r="4"/>'
             '<path d="M17 16.5l-2 6.5M30 16.5l2 6.5"/>',
    "uxo": '<path d="M10 30.5l17-11c5-3.2 11-3 14.5-.5-1.2 4.2-5.3 8.5-10.5 11.6L14 41.5"/>'
           '<path d="M4 38h40"/><path d="M14.5 27.6l5.8 9"/>',
    "cache": '<rect x="6" y="18" width="36" height="22" rx="2"/><path d="M6 26h36M21 22h6"/>'
             '<path d="M12 18l3-8h18l3 8"/>',
    # --- home page actions
    "report": '<path d="M13 6h15l9 9v27H13z"/><path d="M28 6v9h9"/><path d="M18 24h14M18 30h14M18 36h8"/>',
    "brief": '<rect x="10" y="9" width="28" height="33" rx="3"/><path d="M18 9V6h12v3"/>'
             '<path d="M16 21l3 3 5-6M27 21h6M16 32l3 3 5-6M27 32h6"/>',
    "review": '<path d="M8 13h20M8 22h14M8 31h10"/><path d="M27 33l5 5 10-12"/>',
    "map": '<path d="M5 12l12-5 14 5 12-5v29l-12 5-14-5-12 5z"/><path d="M17 7v29M31 12v29"/>',
    "dashboard": '<path d="M6 41h36"/><path d="M11 41V27M20 41V15M29 41V22M38 41V9"/>',
    "tree": '<circle cx="24" cy="10" r="4"/><circle cx="11" cy="37" r="4"/><circle cx="37" cy="37" r="4"/>'
            '<circle cx="24" cy="27" r="3"/><path d="M24 14v10M21.5 29L14 34.5M26.5 29L34 34.5"/>',
    "search": '<circle cx="21" cy="21" r="13"/><path d="M31 31l11 11"/>',
    "warning": '<path d="M24 6l20 35H4z"/><path d="M24 19v11"/><path d="M24 35.5v.1"/>',
    "seed": '<ellipse cx="24" cy="11" rx="16" ry="5"/><path d="M8 11v26c0 2.8 7.2 5 16 5s16-2.2 16-5V11"/>'
            '<path d="M8 24c0 2.8 7.2 5 16 5s16-2.2 16-5"/>',
}


def icon(name: str) -> Markup:
    return Markup(_WRAP.format(_PATHS.get(name, _PATHS["other"])))


# Munition families: (key, display name, icon), and which family each entry
# in data/reference/munition_reference.json belongs to.
FAMILIES = [
    ("mortar", "Mortars", "mortar"),
    ("rocket", "Rockets", "rocket"),
    ("artillery", "Artillery and tank shells", "artillery"),
    ("grenade", "Grenades and RPGs", "grenade"),
    ("mine", "Landmines", "mine"),
    ("cluster", "Cluster munitions", "cluster"),
    ("bomb", "Aircraft bombs", "bomb"),
    ("missile", "Missiles", "missile"),
    ("drone", "Drones and loitering munitions", "drone"),
    ("ied", "Improvised devices (IEDs)", "ied"),
    ("other", "Other and unidentified", "other"),
]
FAMILY_NAME = {k: n for k, n, _i in FAMILIES}

_FAMILY_OF = {
    "rpg_round": "grenade", "tank_gun_projectile": "artillery", "recoilless_munition": "artillery",
    "projectile_generic": "artillery", "submunition": "cluster", "cluster_munition": "cluster",
    "air_delivered_bomb": "bomb", "general_purpose_bomb": "bomb", "guided_bomb": "bomb",
    "manpads_missile": "missile", "atgm": "missile", "missile_generic": "missile",
    "loitering_munition": "drone", "one_way_attack_uav": "drone",
    "landmine": "mine", "uxo_generic": "other", "small_arms_ammunition": "other",
}


def family_of(object_type: str) -> str:
    """Family key for a reference entry (by explicit table, then by name)."""
    if object_type in _FAMILY_OF:
        return _FAMILY_OF[object_type]
    for prefix, fam in (("mortar", "mortar"), ("rocket", "rocket"), ("artillery", "artillery"),
                        ("grenade", "grenade"), ("hand_grenade", "grenade"), ("rifle_grenade", "grenade")):
        if object_type.startswith(prefix):
            return fam
    if object_type.endswith("_mine"):
        return "mine"
    if "ied" in object_type or "improvised" in object_type:
        return "ied"
    if "grenade" in object_type:
        return "grenade"
    return "other"


# Form munition types (app.py _MUNITIONS keys) -> icon.
MUNITION_ICON = {"ied": "ied", "vbied": "vbied", "uxo": "uxo", "mine": "mine", "mortar": "mortar",
                 "rocket": "rocket", "missile": "missile", "artillery": "artillery",
                 "grenade": "grenade", "cache": "cache", "other": "other"}
