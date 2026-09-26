from __future__ import annotations

from urllib.parse import parse_qs, urlparse, unquote

import bs4
import requests

REQUEST_TIMEOUT = 15
CONNECT_TIMEOUT = 5
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
HTML_CAP = 12_000
TEXT_CAP = 8_000
MAX_URLS = 3
_SKIP_HOST_MARKERS = (
    "google.",
    "gstatic.com",
    "googleusercontent.com",
    "g.doubleclick.net",
)

def __remove_cookies_popup(soup):
    cookies_popup = soup.find("div", id="CXQnmb")
    if cookies_popup:
        cookies_popup.decompose()
    dark_area1 = soup.find("div", id="rGDSnb")
    if dark_area1:
        dark_area1.decompose()
    dark_area2 = soup.find("div", id="KjcHPc")
    if dark_area2:
        dark_area2.decompose()
    sponsored_results = soup.find("div", class_="YNk70c CurvIe EjQTId")
    if sponsored_results:
        sponsored_results.decompose()

def __isolate_search_results(soup):
    print("Isolate search results from the soup")
    search_results = soup.find("div", id="rcnt")
    if search_results:
        search_results.extract()
        soup = bs4.BeautifulSoup(search_results.prettify(), "html.parser")
    return soup

def __remove_ads(soup):
    common_ads_classes = ["adsbygoogle", "ad-placeholder", "ad-container", "ad-wrapper", "ad-slot", "ad-slot-wrapper", "ad-slot-container", "ad-slot-inner", "ad-slot-inner-wrapper", "ad-slot-inner-container", "ad-placeholder-top", "ad-placeholder-bottom", "ad-placeholder-top-container", "ad-placeholder-bottom-container", "ad-placeholder-top-container", "ad-placeholder-bottom-container", "ad-placeholder-top-container", "ad-placeholder-bottom-container"]
    for class_ in common_ads_classes:
        elements = soup.find_all(class_=class_)
        for element in elements:
            element.decompose()
    common_ads_ids = ["google_ads_iframe_", "google_ads_frame_", "google_ads_frame_", "google_ads_frame_", "google_ads_frame_", "google_ads_frame_", "google_ads_frame_", "google_ads_frame_", "google_ads_frame_", "google_ads_frame_", "google_ads_iframe_top", "google_ads_iframe_bottom", "google_ads_iframe_top-container", "google_ads_iframe_bottom-container", "google_ads_iframe_top-container", "google_ads_iframe_bottom-container"]
    for id in common_ads_ids:
        element = soup.find(id=id)
        if element:
            element.decompose()

def __remove_search_fields(soup):
    common_search_fields_classes = ["gsc-search-box-tools", "gsc-search-box-tools-top-container", "gsc-search-box-tools-bottom-container", "gsc-search-box-tools-top-container", "gsc-search-box-tools-bottom-container"]
    for class_ in common_search_fields_classes:
        elements = soup.find_all(class_=class_)
        for element in elements:
            element.decompose()
    common_search_fields_ids = ["gsc-search-box-tools-top-container", "gsc-search-box-tools-bottom-container", "gsc-search-box-tools-top-container", "gsc-search-box-tools-bottom-container"]
    for id in common_search_fields_ids:
        element = soup.find(id=id)
        if element:
            element.decompose()

def __remove_submit_buttons(soup):
    common_submit_buttons_classes = ["gsc-search-button-v2", "gsc-search-button-v2-top-container", "gsc-search-button-v2-bottom-container", "gsc-search-button-v2-top-container", "gsc-search-button-v2-bottom-container"]
    for class_ in common_submit_buttons_classes:
        elements = soup.find_all(class_=class_)
        for element in elements:
            element.decompose()
    common_submit_buttons_ids = ["gsc-search-button-v2-top-container", "gsc-search-button-v2-bottom-container", "gsc-search-button-v2-top-container", "gsc-search-button-v2-bottom-container"]
    for id in common_submit_buttons_ids:
        element = soup.find(id=id)
        if element:
            element.decompose()

def check_internet_connectivity():
    """
    Send a ping to google.com to check internet connectivity. 
    Return True if successful, False otherwise.
    Raises an exception if the request fails.
    Use this function to check if the internet is connected before making any requests.
    """
    try:
        response = requests.get(
            "https://www.google.com",
            headers=DEFAULT_HEADERS,
            timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT),
        )
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False
    return False

def search_google(query):
    print(f"Search Google for: {query}")
    params = {
        "client": "firefox-b-d",
        "q": query
    }
    headers = DEFAULT_HEADERS
    base_url = "https://www.google.com/search"
    try:
        response = requests.get(
            base_url,
            params=params,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT),
        )
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None
    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        return None
    soup = bs4.BeautifulSoup(response.text, "html.parser")
    __remove_cookies_popup(soup)
    soup = __isolate_search_results(soup)
    return soup

def remove_classes_and_ids(soup, classses: list[str], ids: list[str]) -> None:
    for class_ in classses:
        elements = soup.find_all(class_=class_)
        for element in elements:
            element.decompose()
    for id in ids:
        element = soup.find(id=id)
        if element:
            element.decompose()

def isolate_classes_and_ids(soup, classses_with_ids: list[tuple[str,str]]):
    if not classses_with_ids:
        return soup
    new_soup = bs4.BeautifulSoup("", "html.parser")
    for class_, id_ in classses_with_ids:
        kwargs = {}
        if class_:
            kwargs["class_"] = class_
        if id_:
            kwargs["id"] = id_
        if not kwargs:
            continue
        elements = soup.find_all(**kwargs)
        for element in elements:
            element.extract()
            new_soup.append(element)
    if not new_soup.contents:
        return soup
    return new_soup

def get_page_content(url):
    try:
        response = requests.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT),
        )
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            return None
        soup = bs4.BeautifulSoup(response.text, "html.parser")
        __remove_ads(soup)
        __remove_search_fields(soup)
        __remove_submit_buttons(soup)
        return soup
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None
    return None


def soup_html(soup, cap: int = HTML_CAP) -> str:
    if soup is None:
        return ""
    text = str(soup)
    if len(text) > cap:
        return text[:cap] + "\n…[truncated]"
    return text


def soup_text(soup, cap: int = TEXT_CAP) -> str:
    if soup is None:
        return ""
    text = soup.get_text("\n", strip=True)
    if len(text) > cap:
        return text[:cap] + "\n…[truncated]"
    return text


def _pairs_from_spec(spec: dict) -> list[tuple[str, str]]:
    raw = spec.get("pairs") or spec.get("keep") or []
    pairs: list[tuple[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pairs.append((str(item[0]).strip(), str(item[1]).strip()))
            elif isinstance(item, dict):
                class_ = str(item.get("class") or item.get("class_") or "").strip()
                id_ = str(item.get("id") or "").strip()
                pairs.append((class_, id_))
    if pairs:
        return [(c, i) for c, i in pairs if c or i]
    classes = [str(c).strip() for c in (spec.get("classes") or []) if str(c).strip()]
    ids = [str(i).strip() for i in (spec.get("ids") or []) if str(i).strip()]
    n = min(len(classes), len(ids))
    return list(zip(classes[:n], ids[:n]))


def apply_markup_filter(soup, spec: dict):
    """Remove or isolate by the model's JSON. Caller must use the return value."""
    if soup is None or not spec:
        return soup
    mode = str(spec.get("mode") or "remove").strip().lower()
    if mode in {"keep", "isolate"}:
        return isolate_classes_and_ids(soup, _pairs_from_spec(spec))
    classes = [str(c).strip() for c in (spec.get("classes") or []) if str(c).strip()]
    ids = [str(i).strip() for i in (spec.get("ids") or []) if str(i).strip()]
    if classes or ids:
        remove_classes_and_ids(soup, classes, ids)
    return soup


def normalize_result_url(href: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith("#"):
        return None
    if href.startswith("/url?"):
        qs = parse_qs(urlparse(href).query)
        href = unquote((qs.get("q") or qs.get("url") or [""])[0])
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    if any(marker in host for marker in _SKIP_HOST_MARKERS):
        return None
    return href


def extract_result_urls(soup, limit: int = MAX_URLS) -> list[str]:
    if soup is None:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for tag in soup.find_all("a", href=True):
        url = normalize_result_url(str(tag.get("href") or ""))
        if url is None or url in seen:
            continue
        seen.add(url)
        found.append(url)
        if len(found) >= limit:
            break
    return found

"""
Expected use case for this module:
1. On loading, check internet connectivity. If connected, display the "Web Search" toggle button right above the chat area
2. If the "Web Search" toggle button is clicked, use the model to build a search query based on chat history and user prompt
3. Use the search_google function to get the search results for the query
4. Pass the results to the model. Use the model to figure out what classes and ids to remove from the results that are irrelevant or non-result areas like Login buttons or such.
5. 
    a. Use the remove_classes_and_ids function to remove the classes and ids obtained from the model from the results
    b. Alternatively, Use the isolate_classes_and_ids function to isolate only the relevant classes and ids obtained from the model from the results
6. Pass the results to the model. Have the model isolate a list of urls from the results that are relevant to the search query and chat history
7. Use the get_page_content function to get the content of the urls. 
8. For each content, follow step 5 to remove irrelevant classes and ids from the content
9. Append resulting contents of each url to a list
10. Pass the content list to the model along with the search query and chat history
11. Now you have the final response from the model after step 10. Display the response in the chat area and log it to be shown in the chat history.
12. Intermediate steps are logged but not shown in the history section.
13. Keep web search toggle on untill user manually turns it off.
14. Web search toggle shows an asterisk icon. Hovering on it tells the user that web search will take time and resources to process and to only use it if internet is needed and connected.
"""