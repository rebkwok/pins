from django import forms
from django.urls import reverse

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Hidden, HTML, Row

from image_uploader_widget.widgets import ImageUploaderWidget

from .models import RecipeBookSubmission

class RecipeBookContrbutionForm(forms.ModelForm):
    recipe_fields = [
        "title", 
        "preparation_time", 
        "cook_time", 
        "servings", 
        "ingredients", 
        "method",
        "submitted_by",
        "profile_image",
        "profile_caption"
    ]
    fields_by_page_type = {
        "single": recipe_fields,
        "single_with_facing": recipe_fields + ["photo", "photo_caption"],
        "double": recipe_fields + ["photo"],
        "photo": ["photo", "photo_caption"],
    }
    optional_fields = ["profile_caption", "photo_caption"]

    def __init__(self, **kwargs):
        page_type = kwargs.pop("page_type", None)
        super().__init__(**kwargs)

        self.fields["page_type"].widget.attrs = {
            "hx-post": reverse("fundraising:update_form_fields"),
            "hx-target": "#submission-form"
        }
        # make all recipe and photo fields not required; validate later based on page_type
        # chosen
        for field in [
            "title", "preparation_time", "cook_time", "servings", "ingredients", "method",
            "submitted_by", "profile_image", "profile_caption",
            "photo", "photo_caption"
            ]:
            self.fields[field].required = False

        if self.instance.page_type:
            layout_fields = self.fields_by_page_type[self.instance.page_type]
        elif page_type is not None:
            layout_fields = self.fields_by_page_type[page_type]
        else:
            layout_fields = []

        self.helper = FormHelper()
        self.helper.form_action = reverse("fundraising:recipe_book_contribution_add")
        self.helper.layout = Layout(
            *self.get_base_layout_fields(),
            *layout_fields,
            Submit('submit', 'Submit')
        )

    def get_base_layout_fields(self):
        return [
            "name",
            "email",
            "page_type"
        ]

    class Meta:
        model = RecipeBookSubmission
        fields = [
            "name", "email",
            "page_type",
            "title", "preparation_time", "cook_time", "servings", "ingredients", "method",
            "submitted_by", "profile_image", "profile_caption",
            "photo", "photo_caption"
        ]
        widgets = {
            'profile_image': ImageUploaderWidget(),
            'photo': ImageUploaderWidget(),
        }
    
    def clean(self):
        page_type = self.cleaned_data["page_type"]
        fields = self.fields_by_page_type[page_type]
        for field in fields:
            if not self.cleaned_data.get(field) and field not in self.optional_fields:
                self.add_error(field, "This field is required.")


class RecipeBookContrbutionEditForm(RecipeBookContrbutionForm):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.helper.form_action = reverse("fundraising:recipe_book_contribution_edit", args=(self.instance.pk,))

    def get_base_layout_fields(self):
        return [
            Hidden("name", self.instance.name),
            Hidden("email", self.instance.email),
            Hidden("page_type", self.instance.page_type),
            HTML(
                "<h2>Your details</h2>"
                f"<label>Name</label><br>{self.instance.name}<br>"
                f"<label>Email</label><br>{self.instance.email}<br>"
                f"<span class='help-block'>Contact us if any of these details are incorrect.</span>"
                "<hr/>"
                "<h2>Submission details</h2>"
                f"<label>Page Type</label><br>{self.instance.page_type_verbose()}<br>"
                f"<span class='help-block'>Contact us if you want to change the page type for this submission.</span>"
            )
        ]