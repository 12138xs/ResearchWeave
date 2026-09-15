from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from apps.materials.pdf_structure import split_pdf_pages
from apps.materials.models import Material, MaterialVersion, Evidence
from apps.materials.structure import build_structure, verified_chunk_text
from apps.assistant.knowledge import material_source, resolve_source, search_knowledge
from apps.assistant.reading import read_source, find_in_source


def sample_pdf():
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))
    for texts in [('1 Method', 'A synthetic equation x=1 and table a b remain original.'),
                  ('Method continues on another page.', '2 Limits', 'R2CWORD limited to smooth solutions.'),
                  ('Limits continue.', 'Repeated step 1 is not a heading.')]:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 12 Tf 50 740 Td ' + ' 0 -24 Td '.join(f'({t}) Tj' for t in texts) + ' ET').encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.add_outline_item('Method', 0)
    writer.add_outline_item('Limits', 1)
    result = BytesIO(); writer.write(result)
    return result.getvalue()


class PDFBoundaryTests(SimpleTestCase):
    def split(self, pages, entries):
        rows=[]; start=1
        for n, text in enumerate(pages, 1):
            end=start+len(text.split('\n'))-1
            rows.append(SimpleNamespace(page=n, text=text, line_start=start, line_end=end))
            start=end+1
        text='\n'.join(pages)
        sections,parts=split_pdf_pages(text,rows,entries)
        self.assertEqual(''.join(p['text'] for p in parts),text)
        return sections,parts

    def test_unknown_duplicate_out_of_order_and_no_outlines_fall_back(self):
        for entries in [[], [{'page':1,'title':'Missing','level':1}],
                        [{'page':None,'title':'Method','level':1}],
                        [{'page':1,'title':'Limits','level':1},{'page':1,'title':'Method','level':1}]]:
            sections,parts=self.split(['Method\nLimits\nmath\n'],entries)
            self.assertEqual(sections,[])
            self.assertTrue(all(not p['title_path'] for p in parts))
        sections,_=self.split(['Method\nMethod'],[{'page':1,'title':'Method','level':1}])
        self.assertEqual(sections,[])

    def test_ambiguous_page_clears_inherited_heading_and_never_loses_text(self):
        sections,parts=self.split(['Method\nx=1\n','unmatched heading\na b\n','continued\n'],
            [{'page':1,'title':'Method','level':1},{'page':2,'title':'Limits','level':1}])
        self.assertEqual(len(sections),1)
        self.assertTrue(parts[0]['title_path'])
        self.assertTrue(all(not p['title_path'] for p in parts[1:]))


class PDFStructureTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user(username='pdf-structure')
        self.material=Material.objects.create(owner=self.user,title='Synthetic PDF',content_type='paper',visibility='private')
        self.version=MaterialVersion.objects.create(material=self.material,number=1,format='pdf',status='needs_review',
            filename='synthetic.pdf',sha256='a'*64,size=1,created_by=self.user)
        for n,text in enumerate(['1 Method\noriginal equation\n', 'continued\n2 Limits\nR2CWORD smooth only\n', 'more limitations\n'],1):
            Evidence.objects.create(version=self.version,ordinal=n,page=n,text=text,review_required=True)
        self.entries=[{'page':1,'title':'Method','level':1},{'page':2,'title':'Limits','level':1}]

    def build(self):
        with patch('apps.materials.pdf_structure.extract_outline',return_value=self.entries):
            return build_structure(self.version.pk)

    def test_pdf_index_preserves_pages_and_fixed_citations(self):
        before=list(self.version.evidence.values())
        old=material_source(self.version.evidence.first())
        index=self.build()
        self.assertEqual(self.build().pk,index.pk)
        self.assertEqual(list(self.version.evidence.values()),before)
        for chunk in index.chunks.select_related('index__version'):
            self.assertEqual(verified_chunk_text(chunk),chunk.text)
        self.assertEqual(resolve_source(old,self.user)['excerpt'],old['excerpt'])
        source=search_knowledge(self.user,{'content_types':['paper']},'R2CWORD')[0]
        self.assertIn('Limits',source['title_path']); self.assertEqual(source['page'],2)
        self.assertIn('需核对',source['location'])
        context=read_source(self.user,{},source,context=True,before=2,after=2)
        self.assertTrue(all('Limits' in row['title_path'] for row in context['sources']))
        self.assertIn('Method',find_in_source(self.user,{},source,query='equation')['sources'][0]['title_path'])
        other=get_user_model().objects.create_user(username='pdf-other')
        self.assertEqual(search_knowledge(other,{},'R2CWORD'),[])
        self.material.internal_ai_blocked=True; self.material.save()
        with self.assertRaises(ValueError): resolve_source(source,self.user)

    def test_rebuild_failure_keeps_old_index_and_changed_evidence_rejected(self):
        index=self.build()
        source=search_knowledge(self.user,{},'R2CWORD')[0]
        with patch('apps.materials.pdf_structure.PARSER_VERSION','next'), patch('apps.materials.pdf_structure.extract_outline',side_effect=ValueError('bad')):
            with self.assertRaises(ValueError): build_structure(self.version.pk)
        self.assertEqual(self.version.structure_indexes.get(is_current=True).pk,index.pk)
        self.version.evidence.filter(page=2).update(text='changed')
        with self.assertRaises(ValueError): resolve_source(source,self.user)

    def test_real_pdf_outline_extraction_and_hash_guard(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        import hashlib
        from pypdf import PdfReader
        from apps.materials.pdf_structure import extract_outline
        data=sample_pdf()
        with TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.pdf'; path.write_bytes(data)
            self.version.sha256=hashlib.sha256(data).hexdigest(); self.version.save()
            self.version.evidence.all().delete()
            for n,page in enumerate(PdfReader(path).pages,1):
                Evidence.objects.create(version=self.version,ordinal=n,page=n,text=page.extract_text(),review_required=True)
            with patch('apps.materials.pdf_structure.get_storage_provider') as storage:
                storage.return_value.resolve.return_value=path
                self.assertEqual(extract_outline(self.version),self.entries)
                index=build_structure(self.version.pk)
                for chunk in index.chunks.select_related('index__version'):
                    self.assertEqual(verified_chunk_text(chunk),chunk.text)
                self.version.sha256='b'*64
                with self.assertRaises(ValueError): extract_outline(self.version)
