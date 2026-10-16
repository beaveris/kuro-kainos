"""Opt-in, one-shot browser location. Never stored in files or share links."""
from math import asin, cos, isfinite, radians, sin, sqrt

import streamlit as st


def validate_location(value):
    if not isinstance(value, dict):
        return None
    try:
        lat, lon, accuracy = (float(value[k]) for k in ('lat', 'lon', 'accuracy'))
        if not all(map(isfinite, (lat, lon, accuracy))):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and accuracy >= 0):
            return None
        return dict(lat=lat, lon=lon, accuracy=accuracy)
    except (KeyError, ValueError, TypeError):
        return None


def distance_km(lat, lon, other_lat, other_lon):
    a, b = radians(lat), radians(other_lat)
    h = sin((b-a)/2)**2 + cos(a)*cos(b)*sin(radians(other_lon-lon)/2)**2
    return 6371.0088 * 2 * asin(sqrt(min(1, max(0, h))))


_LOCATE = st.components.v2.component(
    'fuel_location',
    html='<button type="button">📍 Rasti šalia manęs</button><div role="status" aria-live="polite"></div>',
    css="""
button { min-height:44px; padding:8px 16px; border:1px solid var(--st-primary-color);
border-radius:8px; background:var(--st-secondary-background-color);
color:var(--st-text-color); font:inherit; cursor:pointer; }
button:focus-visible { outline:2px solid var(--st-primary-color); outline-offset:3px; }
div { color:var(--st-text-color); font:inherit; margin-top:6px; }
""",
    js="""
export default function({parentElement, setTriggerValue}) {
  const button = parentElement.querySelector('button');
  const status = parentElement.querySelector('[role=status]');
  let active = true;
  button.onclick = () => {
    if (!window.isSecureContext || !navigator.geolocation) {
      status.textContent = 'Vietos nustatymas nepasiekiamas. Atidarykite HTTPS puslapį naršyklėje arba pasirinkite savivaldybę.';
      return;
    }
    button.disabled = true;
    status.textContent = 'Nustatoma vieta… Jei prašoma, leiskite naršyklei naudoti vietą.';
    navigator.geolocation.getCurrentPosition(position => {
      if (!active) return;
      button.disabled = false;
      status.textContent = '';
      setTriggerValue('position', {
        lat:position.coords.latitude, lon:position.coords.longitude,
        accuracy:position.coords.accuracy
      });
    }, error => {
      if (!active) return;
      button.disabled = false;
      status.textContent = error.code === 1
        ? 'Vietos leidimas nesuteiktas. Leiskite vietą naršyklės nustatymuose arba pasirinkite savivaldybę.'
        : 'Vietos nustatyti nepavyko. Patikrinkite telefono vietos nustatymus ir bandykite dar kartą arba pasirinkite savivaldybę.';
    }, {enableHighAccuracy:true, timeout:15000, maximumAge:60000});
  };
  return () => { active = false; button.onclick = null; };
}
""",
)


def location_button():
    return _LOCATE(key='location_request', on_position_change=lambda: None).position
