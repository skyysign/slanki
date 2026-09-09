from django import forms


class UploadForm(forms.Form):
    title = forms.CharField(
        max_length=180,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Lecture title (optional)"}),
    )
    pdf = forms.FileField(
        label="Lecture PDF",
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf,application/pdf"}),
    )


class CardForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    front = forms.CharField(
        max_length=1000, label="Question", widget=forms.Textarea(attrs={"rows": 3})
    )
    back = forms.CharField(
        max_length=5000, label="Answer", widget=forms.Textarea(attrs={"rows": 5})
    )
    source_quote = forms.CharField(
        max_length=2500,
        required=False,
        label="Supporting excerpt",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    status = forms.ChoiceField(
        choices=[
            ("draft", "Keep as draft"),
            ("accepted", "Accept for export"),
            ("rejected", "Set aside"),
        ]
    )
