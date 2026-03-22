from django.core.validators import FileExtensionValidator

DOCUMENT_EXTENSIONS = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt', 'rtf', 'odt', 'ods']

validate_document_file = FileExtensionValidator(allowed_extensions=DOCUMENT_EXTENSIONS)
