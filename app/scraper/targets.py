"""The Samsung phones to scrape (GSMArena page slugs).

GSMArena's search page sits behind a Cloudflare Turnstile challenge, so we
target the spec pages directly. Each slug was verified to resolve to the
expected model. Add or remove slugs here to change the catalogue.
"""

BASE_URL = "https://www.gsmarena.com/"

TARGET_PHONES: list[str] = [
    # Galaxy S21 series (2021)
    "samsung_galaxy_s21_5g-10626",
    "samsung_galaxy_s21+_5g-10625",
    "samsung_galaxy_s21_ultra_5g-10596",
    # Galaxy S22 series (2022)
    "samsung_galaxy_s22_5g-11253",
    "samsung_galaxy_s22+_5g-11252",
    "samsung_galaxy_s22_ultra_5g-11251",
    # Galaxy S23 series (2023)
    "samsung_galaxy_s23-12082",
    "samsung_galaxy_s23+-12083",
    "samsung_galaxy_s23_ultra-12024",
    "samsung_galaxy_s23_fe-12520",
    # Galaxy S24 series (2024)
    "samsung_galaxy_s24-12773",
    "samsung_galaxy_s24+-12772",
    "samsung_galaxy_s24_ultra-12771",
    # Foldables (2023)
    "samsung_galaxy_z_fold5-12418",
    "samsung_galaxy_z_flip5-12252",
]


def page_url(slug: str) -> str:
    return f"{BASE_URL}{slug}.php"
