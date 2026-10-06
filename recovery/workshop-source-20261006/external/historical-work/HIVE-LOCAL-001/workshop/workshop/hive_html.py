"""Conservative explicit-tag HTML boundaries, not a browser error-recovery parser."""
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
HEADINGS = frozenset('h1 h2 h3 h4 h5 h6'.split())


@dataclass
class Element:
    tag: str
    attrs: dict
    start: int
    start_end: int
    parent: object = None
    end_start: int = 0
    end: int = 0
    text: list = field(default_factory=list)


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source, self.nodes, self.stack = source, [], []
        self.lines = [0]
        for i, ch in enumerate(source):
            if ch == '\n': self.lines.append(i + 1)
        self.feed(source)
        if self.rawdata.strip():
            raise ValueError('unfinished HTML token; use complete tags and escaped text')
        self.close()
        if self.stack:
            raise ValueError(f'unclosed HTML element <{self.stack[-1].tag}>')
        ids = [n.attrs['id'] for n in self.nodes if n.attrs.get('id')]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate HTML id; target and handler bindings must be unique')

    def source_offset(self):
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if len(dict(attrs)) != len(attrs):
            raise ValueError(f'duplicate attributes on <{tag}>')
        start = self.source_offset()
        node = Element(tag, dict(attrs), start, start + len(self.get_starttag_text()),
                       self.stack[-1] if self.stack else None)
        self.nodes.append(node)
        if tag in VOID:
            node.end_start = node.end = node.start_end
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID:
            raise ValueError(f'self-closing non-void HTML <{tag}/> is unsupported; use explicit closing tags')
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1].tag != tag:
            raise ValueError(f'unbalanced HTML closing tag </{tag}>')
        node = self.stack.pop()
        node.end_start = self.source_offset()
        close = self.source.find('>', node.end_start)
        if close < 0: raise ValueError('unfinished HTML closing tag')
        node.end = close + 1

    def handle_data(self, data):
        for node in self.stack:
            if node.tag in HEADINGS: node.text.append(data)

    def scripts(self):
        for node in self.nodes:
            kind = (node.attrs.get('type') or '').lower()
            if node.tag == 'script' and not node.attrs.get('src') and kind in {
                '', 'module', 'text/javascript', 'application/javascript'}:
                yield node, 'module' if kind == 'module' else 'script'

    def handlers(self):
        return {value for node in self.nodes for key, value in node.attrs.items()
                if key.startswith('on') and value}

    def after_element(self, edit):
        if bool(edit.get('element_id')) == bool(edit.get('heading')):
            raise ValueError('select exactly one HTML element_id or direct container heading')
        if edit.get('element_id'):
            matches = [n for n in self.nodes if n.attrs.get('id') == edit['element_id']]
        else:
            matches = []
            for node in self.nodes:
                if node.tag in HEADINGS and ' '.join(''.join(node.text).split()) == edit['heading']:
                    parent = node.parent
                    if parent is not None and parent.tag in {'div', 'section', 'article', 'aside', 'li'}:
                        if all(parent is not x for x in matches): matches.append(parent)
        if len(matches) != 1:
            raise ValueError(f'HTML target must resolve to one complete element; found {len(matches)}')
        node = matches[0]
        if node.tag in {'html', 'body', 'head', 'script', 'style'}:
            raise ValueError(f'unsupported HTML sibling target <{node.tag}>')
        fragment = Document(edit['insert'])
        if any(n.tag in {'html', 'body', 'head', 'script', 'style'} for n in fragment.nodes):
            raise ValueError('HTML sibling insertion accepts balanced markup, not document/script/style blocks')
        if not fragment.nodes:
            raise ValueError('HTML insertion requires a complete element')
        return node.start, node.end
