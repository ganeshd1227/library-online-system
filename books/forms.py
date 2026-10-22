from django import forms
from .models import Book, BookRequest
from .utils import sanitize_book_content


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = [
            'title', 'author', 'isbn', 'category', 'publication_year', 'description',
            'cover_image', 'book_file', 'content_text', 'total_copies', 'available_copies', 'status',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input'}),
            'author': forms.TextInput(attrs={'class': 'form-input'}),
            'isbn': forms.TextInput(attrs={'class': 'form-input'}),
            'category': forms.TextInput(attrs={'class': 'form-input'}),
            'publication_year': forms.NumberInput(attrs={'class': 'form-input'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'content_text': forms.Textarea(attrs={'class': 'form-input', 'rows': 10, 'placeholder': 'Only needed if you are NOT uploading a PDF — plain text/HTML shown in the text reader.'}),
            'total_copies': forms.NumberInput(attrs={'class': 'form-input', 'min': 1}),
            'available_copies': forms.NumberInput(attrs={'class': 'form-input', 'min': 0}),
            'status': forms.Select(attrs={'class': 'form-input'}),
        }

    def clean_title(self):
        title = self.cleaned_data['title'].strip()
        if not title:
            raise forms.ValidationError("Book title cannot be empty.")
        return title

    def clean_content_text(self):
        return sanitize_book_content(self.cleaned_data.get('content_text', ''))

    def clean(self):
        cleaned = super().clean()
        total = cleaned.get('total_copies')
        available = cleaned.get('available_copies')
        if total is not None and available is not None and available > total:
            raise forms.ValidationError("Available copies cannot exceed total copies.")
        return cleaned


class BookSearchForm(forms.Form):
    q = forms.CharField(required=False, label='Search title or author')
    category = forms.CharField(required=False)
    year = forms.IntegerField(required=False, label='Publication year', min_value=1, max_value=9999,
                              error_messages={'invalid': 'Publication year must be a number, e.g. 1998.',
                                              'min_value': 'Enter a valid publication year.',
                                              'max_value': 'Enter a valid publication year.'})
    availability = forms.ChoiceField(required=False, choices=[('', 'Any'), ('AVAILABLE', 'Available only')])

    def clean_q(self):
        from accounts.search_utils import clean_text
        return clean_text(self.cleaned_data.get('q'))

    def clean_category(self):
        from accounts.search_utils import clean_text
        return clean_text(self.cleaned_data.get('category'))


class BookRequestForm(forms.ModelForm):
    class Meta:
        model = BookRequest
        fields = ['requested_title', 'requested_author', 'requested_year']
        widgets = {
            'requested_title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Book title'}),
            'requested_author': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Author name'}),
            'requested_year': forms.NumberInput(attrs={'class': 'form-input', 'placeholder': 'Published year'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['requested_author'].required = True
        self.fields['requested_year'].required = True

    def clean_requested_year(self):
        import datetime
        year = self.cleaned_data['requested_year']
        if year < 1400 or year > datetime.date.today().year:
            raise forms.ValidationError("Enter a valid published year.")
        return year
