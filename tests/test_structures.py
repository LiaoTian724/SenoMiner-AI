import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from rdkit import Chem
from rdkit.Chem import AllChem
from chem_pdf_extractor.structures import generate_conformer, molecular_structure


class StructureTests(unittest.TestCase):
    def source_2d(self):
        mol=Chem.MolFromSmiles('N[C@@H](C)C(=O)O')
        AllChem.Compute2DCoords(mol)
        return Chem.MolToMolBlock(mol)

    def test_generated_conformer_preserves_graph_and_stereochemistry(self):
        source=self.source_2d()
        generated=generate_conformer(source,'123')
        before,after=Chem.MolFromMolBlock(source),Chem.MolFromMolBlock(generated)
        self.assertEqual(Chem.MolToSmiles(before),Chem.MolToSmiles(after))
        self.assertTrue(after.GetConformer().Is3D())
        self.assertGreater(after.GetNumAtoms(),0)

    def test_pubchem_missing_3d_falls_back_and_cache_keeps_provenance(self):
        with tempfile.TemporaryDirectory() as tmp, patch('chem_pdf_extractor.structures._fetch',
              side_effect=[urllib.error.HTTPError('url',404,'No conformer',{},None),self.source_2d()]) as fetch:
            data=molecular_structure('123',Path(tmp))
            self.assertEqual(fetch.call_args_list[0].args,('123','3d'))
            self.assertEqual(fetch.call_args_list[1].args,('123','2d'))
            self.assertEqual(data['origin'],'rdkit_etkdg')
            self.assertTrue(Chem.MolFromMolBlock(data['sdf']).GetConformer().Is3D())
            with patch('chem_pdf_extractor.structures._fetch',side_effect=AssertionError('network')):
                cached=molecular_structure('123',Path(tmp))
            self.assertEqual(cached['origin'],'rdkit_etkdg')
            self.assertEqual(cached['sdf'],data['sdf'])

    def test_pubchem_structure_used_directly_when_available(self):
        sdf=generate_conformer(self.source_2d(),'123')
        with tempfile.TemporaryDirectory() as tmp, patch('chem_pdf_extractor.structures._fetch',return_value=sdf) as fetch:
            data=molecular_structure('123',Path(tmp))
            self.assertEqual(data['origin'],'pubchem_3d')
            self.assertEqual(fetch.call_count,1)

    def test_invalid_identifiers_and_invalid_structures_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch('chem_pdf_extractor.structures._fetch',side_effect=AssertionError('network')):
            with self.assertRaises(ValueError):molecular_structure('../secret',Path(tmp))
        with self.assertRaises(ValueError):generate_conformer('not sdf','123')


if __name__=='__main__':
    unittest.main()
