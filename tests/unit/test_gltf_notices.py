"""A glTF file's copyright and licence notices (:mod:`OpenGLContext.loaders.gltf.notices`).

A file states who made it and on what terms in three places: the asset's own
``copyright``, the ``author``/``license``/``source``/``title`` extras that
Sketchfab and other exporters write beside it, and ``KHR_xmp_json_ld`` packets,
which may be attached to the whole asset or to any one node, mesh, material,
image, scene or animation in it.  Each becomes a :class:`Notice` on the loaded
scene.
"""
import json
import logging

import pytest

from OpenGLContext.loaders import notices as N
from OpenGLContext.loaders.gltf import loader


def load(body):
    return loader.load_gltf(json.dumps(body).encode('utf-8'),
                            base_url='http://example/notices.gltf')


def document(**asset):
    return {'asset': dict({'version': '2.0'}, **asset),
            'scenes': [{'nodes': [0]}], 'scene': 0,
            'nodes': [{'name': 'root'}]}


def with_packets(body, packets, **attached):
    """``body`` carrying ``packets``, each named object pointing at its index."""
    body.setdefault('extensions', {})['KHR_xmp_json_ld'] = {'packets': packets}
    body.setdefault('extensionsUsed', []).append('KHR_xmp_json_ld')
    for where, index in attached.items():
        kind, _, position = where.partition('_')
        target = body['asset'] if kind == 'asset' else body[kind][int(position)]
        target.setdefault('extensions', {})['KHR_xmp_json_ld'] = {'packet': index}
    return body


STATUE = {
    '@context': {'dc': 'http://purl.org/dc/elements/1.1/'},
    'dc:title': 'Athena #3DST8',
    'dc:creator': {'@list': ['Digitage']},
    'dc:rights': 'CC-BY 4.0',
    'dc:source': 'https://skfb.ly/AEw8',
}


class TestTheWholeFile:
    def test_the_asset_copyright_is_the_whole_files_notice(self):
        scene = load(document(copyright='(c) 2026 A. Modeller, CC0'))
        assert scene.notices == [N.Notice(copyright='(c) 2026 A. Modeller, CC0')]
        assert scene.notices[0].covers == ''

    def test_exporter_extras_say_who_what_and_on_what_terms(self):
        scene = load(document(extras={
            'author': 'Digitage (https://sketchfab.com/digitage)',
            'license': 'CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)',
            'source': 'https://sketchfab.com/3d-models/athena',
            'title': 'Athena #3DST8'}))
        [notice] = scene.notices
        assert notice.title == 'Athena #3DST8'
        assert notice.creator == 'Digitage (https://sketchfab.com/digitage)'
        assert notice.licence.startswith('CC-BY-4.0')
        assert notice.source == 'https://sketchfab.com/3d-models/athena'

    def test_a_packet_on_the_asset_adds_to_the_whole_files_notice(self):
        body = with_packets(document(copyright='(c) The Builder'), [STATUE],
                            asset=0)
        [notice] = load(body).notices
        assert notice.copyright == '(c) The Builder'
        assert notice.title == 'Athena #3DST8'
        assert notice.licence == 'CC-BY 4.0'

    def test_a_file_that_says_nothing_has_no_notices(self):
        assert load(document()).notices == []

    def test_extras_that_are_not_text_are_not_a_notice(self):
        assert load(document(extras={'author': 7, 'title': ['x']})).notices == []


class TestOnePart:
    def test_a_packet_on_a_node_covers_that_node_by_name(self):
        body = document(copyright='(c) The Builder')
        body['nodes'].append({'name': 'athena_parthenos'})
        body['scenes'][0]['nodes'].append(1)
        body = with_packets(body, [STATUE], nodes_1=0)
        whole, part = load(body).notices
        assert whole.covers == ''
        assert part.covers == 'athena_parthenos'
        assert part.title == 'Athena #3DST8'
        assert part.creator == 'Digitage'
        assert part.source == 'https://skfb.ly/AEw8'

    def test_one_packet_on_many_parts_is_one_notice_naming_them(self):
        body = document()
        body['nodes'] = [{'name': 'column_%d' % i} for i in range(3)]
        body['scenes'][0]['nodes'] = [0, 1, 2]
        body = with_packets(body, [STATUE], nodes_0=0, nodes_1=0, nodes_2=0)
        [notice] = load(body).notices
        assert notice.covers == 'column_0, column_1, column_2'

    def test_a_long_list_of_parts_is_cut_short(self):
        body = document()
        body['nodes'] = [{'name': 'column_%d' % i} for i in range(40)]
        body['scenes'][0]['nodes'] = list(range(40))
        body = with_packets(body, [STATUE],
                            **{'nodes_%d' % i: 0 for i in range(40)})
        [notice] = load(body).notices
        assert notice.covers.startswith('column_0, column_1')
        assert notice.covers.endswith('and 32 more')

    def test_a_part_with_no_name_is_named_by_its_kind_and_index(self):
        body = document()
        body['materials'] = [{}]
        body = with_packets(body, [STATUE], materials_0=0)
        [notice] = load(body).notices
        assert notice.covers == 'material 0'

    def test_a_packet_index_out_of_range_is_reported_and_skipped(self, caplog):
        body = with_packets(document(), [STATUE], nodes_0=5)
        with caplog.at_level(logging.WARNING):
            assert load(body).notices == []
        assert 'KHR_xmp_json_ld' in caplog.text


class TestXMPValues:
    @pytest.mark.parametrize('value, text', [
        ('plain', 'plain'),
        ({'@value': 'typed'}, 'typed'),
        ({'@list': ['Ann', 'Bob']}, 'Ann, Bob'),
        ({'@set': ['Ann']}, 'Ann'),
        ({'@type': 'rdf:Alt', 'rdf:_1': {'@value': 'Title', '@language': 'en'},
          'rdf:_2': {'@value': 'Titre', '@language': 'fr'}}, 'Title'),
        ({'@type': 'rdf:Alt', 'rdf:_1': 'Plain alternative'}, 'Plain alternative'),
        (12, ''),
        (None, ''),
        ({'@list': [{'@value': 'Ann'}, 3]}, 'Ann'),
    ])
    def test_each_shape_reads_as_text(self, value, text):
        from OpenGLContext.loaders.gltf.notices import xmp_text
        assert xmp_text(value) == text

    def test_usage_terms_are_the_licence_when_no_rights_are_given(self):
        body = with_packets(document(), [{
            'xmpRights:UsageTerms': 'Free with attribution'}], asset=0)
        [notice] = load(body).notices
        assert notice.licence == 'Free with attribution'


class TestTheText:
    def test_the_whole_file_comes_first_then_each_part(self):
        text = N.notices_text([
            N.Notice(copyright='(c) The Builder'),
            N.Notice(covers='athena_parthenos', title='Athena #3DST8',
                     creator='Digitage', licence='CC-BY 4.0',
                     source='https://skfb.ly/AEw8'),
        ])
        assert text.splitlines() == [
            'This file',
            '    (c) The Builder',
            '',
            'athena_parthenos',
            '    Athena #3DST8',
            '    By Digitage',
            '    Licence: CC-BY 4.0',
            '    Source: https://skfb.ly/AEw8',
        ]

    def test_no_notices_says_so(self):
        assert N.notices_text([]) == N.NONE

    def test_a_notice_with_only_a_covering_says_nothing(self):
        assert not N.Notice(covers='a part')
        assert N.Notice(title='x')
