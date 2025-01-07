import os
import re
import urllib.request
import fontforge
import argparse
import xml.dom.minidom 
from functools import reduce


def save_file(filepath, content):
    dirname = os.path.dirname(filepath)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


def camel(match):
    return match.group(1) + match.group(2).upper()


def to_camel_case(string):
    return re.sub(r'(.*?)[-_](\w)', camel, string)


def combine_dict(a, b):
    return {**a, **b}


def combine_tables(*tables):
    result = {}
    keys = set([key for table in tables for key in table.keys()])

    for key in keys:
        result[key] = reduce(combine_dict, [t.get(key,{}) for t in tables]) 

    return result


def create_glyps(codes):
    result = {}
    for index, code in codes:
        result[index] = {'glyph': index}
    return result


def generate_svgfont(font, svgfilepath):
    font.generate(svgfilepath)
    return svgfilepath
    

def get_code(glyph):
    return glyph.codepoint[2:].lower()


def get_glyphs(font):
    return [g for g in list(font.glyphs()) if g.codepoint]


def generate_svgs(glyphs, svgdirectory):
    result = {}
    index = 1

    for glyph in glyphs:
        index_str = str(index)
        svgfile = svgdirectory + index_str + '.svg'
        print('svgfile: ', svgfile)
        glyph.export(svgfile)
        result[index_str] = { 'svgfile': svgfile }
        index += 1
    return result


def extract_from_glyph(glyph):
    return {
        'code': get_code(glyph),
        'glyphname': glyph.glyphname
    }


def extract_from_glyphs(glyphs):
    result = [extract_from_glyph(g) for g in glyphs]
    return {g['code']:g for g in result}
 

def extract_from_css(cssfilepath):
    with open(cssfilepath, 'r') as f:
        css = f.read()

    names = re.findall(r'nf-(.*):', css)
    codes = re.findall(r'"\\(.*)"', css)
    groups, iconnames = zip(*[n.split('-') for n in names])

    fields = ['code', 'name', 'group', 'iconname']
    field_values = zip(codes, names, groups, iconnames)

    data = [dict(zip(fields, values)) for values in field_values]
    return {record['code']:record for record in data}


def extract_from_svg(svgfilepath):
    svg = xml.dom.minidom.parse(svgfilepath)
    viewbox = svg.getElementsByTagName('svg')[0].getAttribute('viewBox')
    paths = [p.getAttribute('d') for p in svg.getElementsByTagName('path')]

    return { 'viewbox': viewbox, 'paths': paths }


def extract_from_svgs(svgfiles):
    files = [(code, value['svgfile']) for (code, value) in svgfiles.items()]
    return { code:extract_from_svg(fn) for (code, fn) in files }


def remove_unnamed(data):
    return {k:v for (k, v) in data.items() if v.get('name')}


modifiers = {
    'camelcase': to_camel_case,
    'upper': lambda x: x.upper(),
    'lower': lambda x: x.lower(),
}


class FieldFormatter:
    def __init__(self, field_description, rename=True):
        field = field_description.split(':')
        self.name = field[0]
        if rename:
            self.new_name = field[1] if len(field) > 1 else field[0]
            self.modifiers = [modifiers[m] for m in field[2:] if m in modifiers]
        else:
            self.new_name = field[0]
            self.modifiers = [modifiers[m] for m in field[1:] if m in modifiers]
    
    def apply_modifiers(self, value):
        for m in self.modifiers:
            value = m(value)
        return value
    
    def format(self, record):
        value = record.get(self.name, None)
        return (self.new_name, self.apply_modifiers(value)) if value else None
    

class FilenameFormatter:
    def __init__(self, filename):
        self.format_string = re.sub(r'\{(\w+)[a-zA-Z:]*\}', r'{\1}', filename)
        field_descriptions = re.findall(r'\{([a-zA-Z:]+)\}', filename)
        self.field_formatters = [FieldFormatter(fd, False) for fd in field_descriptions]

    def format(self, record):
        formatted_fields = [f.format(record) for f in self.field_formatters] 
        replacements = {f[0]:f[1] for f in formatted_fields if f}
        return self.format_string.format(**replacements)


class RecordFormatter:
    def __init__(self, field_descriptions):
        self.field_formatters = [FieldFormatter(fd, True) for fd in field_descriptions]

    def format(self, record):
        formatted_fields = [f.format(record) for f in self.field_formatters]
        return {f[0]:f[1] for f in formatted_fields if f}


def match_filters(record, filters):
    for f in filters:
        if not re.match(f[1], record[f[0]]):
            return False
    return True

def filter_records(data, filters):
    return [record for record in data if match_filters(record, filters)]

def create_raw_data(resources, force_download=False, svgdir='svg'):
    print('fontfile path: ', resources['fontfile']['filepath'])
    print('cssfile path: ', resources['cssfile']['filepath'])
    
    font = fontforge.open(resources['fontfile']['filepath'])
    table = extract_from_css(resources['cssfile']['filepath'])
    print('Extracted iconinfo from cssfile:',
            resources['cssfile']['filepath'])

    glyph_data = extract_from_glyphs(get_glyphs(font))
    print('Extracted iconinfo from fontfile:',
            resources['fontfile']['filepath'])
    
    svgdir = os.path.join(svgdir, '')
    os.makedirs(svgdir, exist_ok=True)
    svg_files = generate_svgs(get_glyphs(font), svgdir)
    print('Generated svgicons from fontfile:',
            resources['fontfile']['filepath'], '=>', svgdir+'*.svg')

    return True

def split_path(path, extension=None, default_filename=None):
    if extension and default_filename and not path.endswith(extension):
        path = os.path.join(path, default_filename+extension)

    dirname, filename = os.path.split(path)
    while r'{' in dirname:
        dirname, fn = os.path.split(dirname)
        filename = os.path.join(fn, filename)
    return (dirname, filename)


def export_svg(filepath, data, record_formatter):
    import shutil
    base_dir, file_name = split_path(filepath, '.svg', '{code}_{name}')
    
    filename_formatter = FilenameFormatter(os.path.join(base_dir, file_name))

    for record in data:
        filename = filename_formatter.format(record)
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        shutil.copy(record['svgfile'], filename)
        record['svgfile'] = filename
    return data


def parse_args():
    fields = ['code', 'name', 'glyphname', 'iconname', 'group',
                'glyph', 'svgfile', 'viewbox', 'paths']

    parser = argparse.ArgumentParser(
        description='Convert nerd-font-icons to SVG',
        formatter_class=argparse.RawTextHelpFormatter)

    #parser.add_argument('--download', default='/tmp/nerdfonts_dl/', type=str,
    parser.add_argument('--download', default='/home/e/Завантаження/Firefox_Downloads/nerd-fonts-3.3.0/', type=str,
        help='Download Directory for nerd-fonts resources (ttf/css)')

    parser.add_argument('--fields', default=fields, type=str, nargs='*',
        metavar='',
        help='One or more fields that will be included in the '
        'output file.\n A field can be specified in the form of'
        'FIELDNAME[:REPLACEMENT[:MODIFIER]]\n' 
        'e.g. name:iconname:camelcase will include the "name"-field,\n'
        'rename it to "iconname" and convert the fieldvalues to camelcase.\n'
        'Possible FIELDNAMEs are '+', '.join(fields))

    parser.add_argument('--filter', nargs=2, type=str,
        metavar=('FIELD', 'REGEX'), action='append',
        help='Filter FIELD by REGEX (can be used multiple times)')

    parser.add_argument('-o', '--output',
        type=str, nargs='+', action='append',
        metavar=('FORMAT', 'FILEPATH'), help='Output')
    return parser.parse_args()


def main():
    args = parse_args()
    resources = {
        'fontfile': {
            #'url': base_url+'/src/glyphs/Symbols-2048-em%20Nerd%20Font%20Complete.ttf',
            #'filepath': os.path.join(args.download, 'Symbols-2048-em_Nerd_Font_Complete.ttf')
            'filepath': os.path.join(args.download,
                '3270NerdFont-Regular.ttf')
                #'3270NerdFont-Condensed.ttf')
                #'3270NerdFont-SemiCondensed.ttf')
                #'3270NerdFontMono-Condensed.ttf')
                #'3270NerdFontMono-Regular.ttf')
                #'3270NerdFontMono-SemiCondensed.ttf')
                #'3270NerdFontPropo-Condensed.ttf')
                #'3270NerdFontPropo-Regular.ttf')
                #'3270NerdFontPropo-SemiCondensed.ttf')
            },
        'cssfile': {
            #'url': base_url+'/css/nerd-fonts-generated.css',
            #'filepath': os.path.join(args.download, 'nerd-fonts-generated.css')
            'filepath': os.path.join(args.download,
                'css/nerd-fonts-generated.css')
            }
        }
    #raw_data = create_raw_data(resources, False, '/tmp/nerdfonts_svg/')
    raw_data = create_raw_data(resources, False, '/home/e/Завантаження/Firefox_Downloads/nerd-fonts-3.3.0/nerdfonts_svg/')
    print('done!')


if __name__ == '__main__':
    main()

# sudo apt-get install python3-fontforge
# python3 nerdconvert.py -o svg svgfiles/{name:camelcase}_{code}.svg

# or
# https://github.com/fontforge/fontforge/issues/2597
# fontforge -lang=py -script nerdconvert.py -o svg svgfiles/{name:camelcase}_{code}.svg


