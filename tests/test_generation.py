import unittest
from axdesk.generation import validate_output


class QuoteValidation(unittest.TestCase):
    evidence = [{'doc_id':'SOP-01','quote':'Missing readings must stay blank.'}]

    def test_exact_quote_passes(self):
        result, source = validate_output('{"doc_id":"SOP-01","quote":"Missing readings must stay blank.","answer":"Keep missing readings blank."}', self.evidence)
        self.assertEqual(source['doc_id'], 'SOP-01')

    def test_hallucinated_quote_rejected(self):
        with self.assertRaises(ValueError):
            validate_output('{"doc_id":"SOP-01","quote":"Missing readings should be zero.","answer":"Use zero."}', self.evidence)

    def test_unknown_document_rejected(self):
        with self.assertRaises(ValueError):
            validate_output('{"doc_id":"SOP-99","quote":"Missing readings must stay blank.","answer":"Keep blank."}', self.evidence)

    def test_type_confusion_rejected(self):
        with self.assertRaises(ValueError):
            validate_output('{"doc_id":"SOP-01","quote":"Missing readings must stay blank.","answer":42}', self.evidence)

    def test_second_paragraph_same_document_is_valid(self):
        citations = self.evidence + [{'doc_id':'SOP-01','quote':'A person must review the data.'}]
        _, source = validate_output('{"doc_id":"SOP-01","quote":"A person must review the data.","answer":"Review the data."}', citations)
        self.assertEqual(source['quote'], 'A person must review the data.')


if __name__ == '__main__':
    unittest.main()
