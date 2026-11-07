"""Read-only searches of EXT's public HTML search pages."""
import re
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

BASE_URL = 'https://ext.to'
MAX_PAGE_BYTES = 4 * 1024 * 1024


class SearchError(ValueError):
    """The search provider could not return usable results."""


class _ResultsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = {'text': '', 'links': [], 'class': attrs.get('class', '')}
        elif tag == 'a' and self.cell is not None:
            self.link = {'href': attrs.get('href', ''), 'text': ''}
        elif tag == 'br' and self.cell is not None:
            self.cell['text'] += ' '

    def handle_data(self, data):
        if self.cell is not None:
            self.cell['text'] += data
        if self.link is not None:
            self.link['text'] += data

    def handle_endtag(self, tag):
        if tag == 'a' and self.link is not None:
            self.cell['links'].append(self.link)
            self.link = None
        elif tag in ('td', 'th') and self.cell is not None:
            self.row.append(self.cell)
            self.cell = None
            self.link = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None
            self.cell = None
            self.link = None


def _text(value):
    # Keep remote text on one terminal line and remove control characters.
    return ' '.join(''.join(c for c in value if c.isprintable() or c.isspace()).split())


def parse_results(html):
    parser = _ResultsParser()
    parser.feed(html)
    results = []
    seen = set()
    for row in parser.rows:
        for cell in row:
            for link in cell['links']:
                url = urljoin(BASE_URL, link['href'])
                parts = urlsplit(url)
                if (parts.scheme != 'https' or parts.netloc != 'ext.to'
                        or not re.fullmatch(r'/[^/]+-\d+/', parts.path)):
                    continue
                title = _text(link['text'])
                if not title or url in seen:
                    continue
                seen.add(url)
                size = next((_text(c['text']) for c in row
                             if re.fullmatch(r'[\d.,]+\s*[KMGTPE]?i?B', _text(c['text']), re.I)), None)
                def count(css):
                    value = next((_text(c['text']) for c in row if css in c['class'].split()), '')
                    value = value.replace(',', '').replace(' ', '')
                    return int(value) if value.isdecimal() else None
                results.append(dict(title=title, url=url, size=size,
                                    seeders=count('text-success'), leechers=count('text-danger')))
    if not results and not re.search(r'no (?:results|torrents)(?:\s+were)?(?:\s+found)?|nothing found', html, re.I):
        raise SearchError('EXT returned an unrecognized page (possibly an access challenge or changed layout)')
    return results


def search(query, page=1, limit=20):
    query = query.strip()
    if not query:
        raise ValueError('Search query cannot be empty')
    if page < 1 or not 1 <= limit <= 100:
        raise ValueError('Page must be positive and limit must be between 1 and 100')
    url = BASE_URL + '/search/?' + urlencode({'q': query, 'page': page})
    request = Request(url, headers={'User-Agent': 'terrence/0.1.0', 'Accept': 'text/html'})
    try:
        with urlopen(request, timeout=20) as response:
            data = response.read(MAX_PAGE_BYTES + 1)
            if len(data) > MAX_PAGE_BYTES:
                raise SearchError('EXT search response exceeds 4 MiB')
            html = data.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
    except HTTPError as error:
        raise SearchError(f'EXT search failed: HTTP {error.code}; check site access and network policy') from error
    except (URLError, OSError) as error:
        raise SearchError(f'Could not reach EXT: {error.reason if isinstance(error, URLError) else error}') from error
    return parse_results(html)[:limit]
