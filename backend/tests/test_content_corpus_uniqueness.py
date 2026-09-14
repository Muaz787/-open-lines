"""No two marketing pages may be substantially the same page.

WHY THIS IS A TEST AND NOT A HABIT
Google's doorway-page policy is not about page count, it is about many similar
pages that each add little. The programmatic families here are built to grow to
a couple of hundred pages, which is fine — right up until two of them make the
same argument under different titles.

Judgement does not catch this. Writing five pages in one sitting, the author
produced two identical section headings and a pair at 0.36 word overlap, and
noticed neither until a script said so. That is the entire case for measuring
it on every run instead of at the end.

WHAT COUNTS AS A DUPLICATE SIGNAL
Search engines look at title, heading and body overlap. So does this: identical
<title>s, identical H1s, identical section headings, identical FAQ questions,
and pages whose vocabulary is mostly shared. Each check names the offending
pair, because "something is too similar" is not actionable at 3am.
"""
import itertools
import re
from pathlib import Path

import pytest

FE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "app"

#: A copied page scores far above this; genuinely adjacent topics — after-hours
#: and busy-periods, say — sit around 0.33. Set with headroom so a legitimate
#: new page on a neighbouring subject does not fail, while a page written by
#: find-and-replace does.
MAX_SIMILARITY = 0.34

#: Below this a page is not saying enough to deserve its own URL.
MIN_CONTENT_WORDS = 130

_STOP = set(
    "the a an and or of to in for it is are be with that this your you our on at "
    "as if not what how do does can will they them their there here from by we us "
    "have has had was were been but so than then when which who whom into out up "
    "about over under more most some any all one two each other also just only".split()
)


def _strings(src: str) -> list[str]:
    """Every single-quoted literal in a TS source, unescaped."""
    return [m.group(1).replace("\\'", "'")
            for m in re.finditer(r"'((?:[^'\\]|\\.)*)'", src)]


def _field(src: str, name: str) -> list[str]:
    return [m.group(1).replace("\\'", "'")
            for m in re.finditer(name + r": '((?:[^'\\]|\\.)*)'", src)]


def _words(text: str) -> set[str]:
    text = re.sub(r"[^A-Za-z' ]", " ", text.lower())
    return {w for w in text.split() if len(w) > 3 and w not in _STOP}


#: Keys whose values are navigation furniture rather than the page's argument:
#: cross-links, their labels, and the shared CTA strip every page carries. A
#: crawler evaluates a page's MAIN content, so counting shared chrome as body
#: text both inflates the score for genuinely distinct pages and leaves less
#: room to detect the duplication that matters. Measured on insurance + legal,
#: 29 of the identical strings between them were furniture of exactly this kind.
_CHROME_KEYS = ("href", "label", "sub", "ctaHeading", "ctaSub", "trustLine")


def _content_strings(src: str) -> list[str]:
    """Every quoted literal EXCEPT navigation chrome and code identifiers.

    Deliberately conservative: it drops what is provably furniture (a key from
    _CHROME_KEYS, an import path, a route) and keeps everything else, so a real
    duplicated paragraph can never be excluded by accident.
    """
    out = []
    for m in re.finditer(r"(?:(\w+)\s*:\s*)?'((?:[^'\\]|\\.)*)'", src):
        key, value = m.group(1), m.group(2).replace("\\'", "'")
        if key in _CHROME_KEYS:
            continue
        if value.startswith(("/", "./", "../", "http")) or "/" in value and " " not in value:
            continue
        out.append(value)
    return out


def _split_by_slug(src: str) -> dict[str, str]:
    out, cur, slug = {}, [], None
    for line in src.splitlines():
        m = re.match(r"\s*slug: '([a-z0-9-]+)',", line)
        if m:
            if slug:
                out[slug] = "\n".join(cur)
            slug, cur = m.group(1), []
        elif slug is not None:
            cur.append(line)
    if slug:
        out[slug] = "\n".join(cur)
    return out


def _corpus() -> dict[str, str]:
    """Every generated marketing page, keyed by a readable id.

    Three families, because the plan grows all three: /learn articles and
    /integrations entries live in data files, while the vertical landing pages
    are one file each.
    """
    pages: dict[str, str] = {}

    for rel, prefix in (("learn/learn-data.ts", "learn"),
                        ("integrations/integrations-data.ts", "integrations")):
        path = FE / rel
        if not path.exists():
            continue
        for slug, block in _split_by_slug(path.read_text()).items():
            pages[f"{prefix}/{slug}"] = block

    for page in sorted(FE.glob("*/page.tsx")):
        src = page.read_text()
        if "VerticalLanding" in src:
            pages[f"vertical/{page.parent.name}"] = src

    return pages


CORPUS = _corpus()


def test_the_corpus_was_actually_found():
    """A parser that silently matches nothing passes every test below it."""
    assert len(CORPUS) >= 30, f"only found {len(CORPUS)} pages — the parser is broken"
    families = {k.split("/")[0] for k in CORPUS}
    assert families == {"learn", "integrations", "vertical"}, families


@pytest.mark.parametrize("field,label", [
    ("metaTitle", "<title>"),
    ("h1", "H1"),
])
def test_no_two_pages_share_a(field, label):
    """The two strongest duplicate-content signals a crawler reads."""
    seen: dict[str, str] = {}
    clashes = []
    for page, src in CORPUS.items():
        for value in _field(src, field):
            key = value.strip().lower()
            if key in seen and seen[key] != page:
                clashes.append(f"{label} {value!r}: {seen[key]} + {page}")
            seen[key] = page
    assert not clashes, "duplicate " + label + ":\n  " + "\n  ".join(clashes)


def test_no_two_pages_share_a_section_heading():
    """Identical headings are the templating smell — the signal that one page
    was produced from another rather than written."""
    seen, clashes = {}, []
    for page, src in CORPUS.items():
        for h in _field(src, "heading"):
            key = h.strip().lower()
            if key in seen and seen[key] != page:
                clashes.append(f"{h!r}: {seen[key]} + {page}")
            seen[key] = page
    assert not clashes, "duplicate section headings:\n  " + "\n  ".join(clashes)


def test_no_two_pages_ask_the_same_faq_question():
    """Duplicated FAQ entries also duplicate the FAQPage structured data, which
    is the part search engines actually lift."""
    seen, clashes = {}, []
    for page, src in CORPUS.items():
        for q in _field(src, "q"):
            key = q.strip().lower()
            if key in seen and seen[key] != page:
                clashes.append(f"{q!r}: {seen[key]} + {page}")
            seen[key] = page
    assert not clashes, "duplicate FAQ questions:\n  " + "\n  ".join(clashes)


def test_no_page_is_substantially_another_page():
    """Body overlap, which catches the case where every heading was reworded
    but the argument underneath is the same one."""
    vocab = {p: _words(" ".join(_content_strings(src))) for p, src in CORPUS.items()}
    over = []
    for a, b in itertools.combinations(sorted(vocab), 2):
        wa, wb = vocab[a], vocab[b]
        if not wa or not wb:
            continue
        j = len(wa & wb) / len(wa | wb)
        if j > MAX_SIMILARITY:
            over.append(f"{j:.2f}  {a} + {b}")
    assert not over, (
        f"pages above {MAX_SIMILARITY} word overlap — one of each pair probably "
        f"should not exist:\n  " + "\n  ".join(sorted(over, reverse=True)))


def test_no_page_is_too_thin_to_deserve_a_url():
    thin = []
    for page, src in sorted(CORPUS.items()):
        n = len(_words(" ".join(_content_strings(src))))
        if n < MIN_CONTENT_WORDS:
            thin.append(f"{n:>4} words  {page}")
    assert not thin, (
        f"pages under {MIN_CONTENT_WORDS} distinct content words:\n  " + "\n  ".join(thin))
