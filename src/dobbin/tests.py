import unittest
import doctest
import tempfile
import transaction

OPTIONFLAGS = (doctest.ELLIPSIS |
               doctest.NORMALIZE_WHITESPACE)

def test_suite():
    database_path = tempfile.NamedTemporaryFile().name

    globs = dict(
        database_path=database_path,
        transaction=transaction,
        )

    return unittest.TestSuite([
        doctest.DocFileSuite(
            'README.txt',
            optionflags=OPTIONFLAGS,
            globs=globs,
            package="dobbin"),
        ])

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
