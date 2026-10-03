import base64
import tempfile
import unittest
from services.api.documents import DocumentStore

class DocumentsTest(unittest.TestCase):
    def test_content_addressed_documents_keep_links_and_validate_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            store=DocumentStore(root)
            doc=store.put({'filename':'title.txt','content_base64':base64.b64encode(b'Fixture title evidence').decode(),'property_id':'08031-0001'})
            again=store.put({'filename':'duplicate.txt','content_base64':base64.b64encode(b'Fixture title evidence').decode(),'episode_id':'episode-1'})
            self.assertEqual(doc['id'],again['id'])
            self.assertEqual(len(again['links']),2)
            self.assertEqual(len(DocumentStore(root).list('08031-0001')['items']),1)
            self.assertEqual(base64.b64decode(store.get(doc['id'])['content_base64']),b'Fixture title evidence')
            with self.assertRaises(ValueError):store.get('../../secret')
            with self.assertRaises(ValueError):store.put({'filename':'../secret','content_base64':'YQ=='})

if __name__=='__main__':unittest.main()
