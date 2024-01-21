from typing import Any
from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Hidden, HTML, Div

from .models import RecipeBookSubmission, PAGE_TYPE_COSTS


class CustomFileInput(forms.widgets.ClearableFileInput):
    input_text = "Choose another"
    template_name = 'fundraising/widgets/image_file_input.html'


class RecipeBookContrbutionForm(forms.ModelForm):
    email1 = forms.EmailField(label="Email (again)")

    recipe_fields = [
        HTML("<h2>Recipe Details</h2><hr>"),
        "title", 
        "preparation_time", 
        "cook_time", 
        "servings", 
        "ingredients", 
        Div("method", HTML("<span id='method_ch_count' class='help-block'>Character count: 0</span>")),
        HTML("<h2>Profile</h2><hr>"),
        "submitted_by",
        "profile_image",
        Div("profile_caption", HTML("<span id='profile_caption_ch_count' class='help-block'>Character count: 0</span>")),
    ]
    photo_fields = ["photo", "photo_title", "photo_caption"]
    fields_by_page_type = {
        "single": recipe_fields,
        "single_with_facing": [*recipe_fields, HTML("<h2>Facing Full-Page Photo</h2><hr>"), *photo_fields],
        "double": recipe_fields + [
            HTML("<h2>Additional Photo on second page (optional)</h2><hr>"),
            "photo"
        ],
        "photo": [HTML("<h2>Full-Page Photo</h2><hr>"), *photo_fields],
    }

    recipe_required =[
        "title", "preparation_time", "cook_time", "servings", "ingredients", "method",
        "submitted_by", "profile_image"
    ]

    required_fields_by_page_type = {
        "single": recipe_required,
        "double": recipe_required,
        "single_with_facing": [*recipe_required, "photo", "photo_title"],
        "photo": ["photo", "photo_title"]
    }

    def __init__(self, **kwargs):
        page_type = kwargs.pop("page_type", None)
        super().__init__(**kwargs)

        self.fields["page_type"].widget.attrs = {
            "hx-post": reverse("fundraising:update_form_fields"),
            "hx-target": "#submission-form",
        }
        page_type_choices = [
            (choice_k, f"{choice_v} - £{PAGE_TYPE_COSTS[choice_k]}") 
            for (choice_k, choice_v) in RecipeBookSubmission.page_types
        ]
        self.fields["page_type"].choices = tuple([("", "---"), *page_type_choices])
        # make all recipe and photo fields not required; validate later based on page_type
        # chosen
        required_fields = ["name", "email", "email1", "page_type", *self.required_fields_by_page_type.get(page_type, [])]
        for field in required_fields:
            self.fields[field].required = True

        page_type = self.instance.page_type or page_type
        layout_fields = self.fields_by_page_type.get(page_type, [])
        
        if page_type != "photo":
            method_field = self.fields["method"]
            max_method_count = 1200
            if page_type in ["single", "single_with_facing"]:
                method_field.help_text += (
                    ". Enter a maximum of 1200 characters for a single-page recipe. "
                    "If you need more space (up to 3000 characters), please choose "
                    "the double page option."
                )
            elif page_type == "double":
                max_method_count = 3000
                method_field.help_text += ". Maximum of 3000 characters."

            method_field.widget.attrs.update({
                "maxlength": max_method_count,
                "hx-get": reverse("fundraising:method_char_count") + f"?max={max_method_count}",
                "hx-target": "#method_ch_count",
                "hx-trigger": "keyup"
            })

            profile_caption = self.fields["profile_caption"]
            profile_caption.widget.attrs.update({
                "hx-get": reverse("fundraising:profile_caption_char_count") + f"?max=300",
                "hx-target": "#profile_caption_ch_count",
                "hx-trigger": "keyup"
            })
            profile_caption.help_text += ". Maximum of 300 characters."


        self.helper = FormHelper()
        self.helper.form_action = reverse("fundraising:recipe_book_contribution_add")
        self.helper.layout = Layout(
            *self.get_base_layout_fields(),
            *layout_fields,
            *self.get_final_fields()
        )

    def get_base_layout_fields(self):
        return [
            "name",
            "email",
            "email1",
            "page_type"
        ]

    def get_final_fields(self):
        return [
            Submit('submit', 'Submit')
        ]
    
    def clean_email1(self):
        if self.cleaned_data["email"] != self.cleaned_data["email1"]:
            raise ValidationError("Email fields do not match")

    class Meta:
        model = RecipeBookSubmission
        fields = [
            "name", "email",
            "page_type",
            "title", "preparation_time", "cook_time", "servings", "ingredients", "method",
            "submitted_by", "profile_image", "profile_caption",
            "photo",  "photo_title", "photo_caption"
        ]
        widgets = {
            'profile_image': CustomFileInput(),
            'photo': CustomFileInput(),
        }


class RecipeBookContrbutionEditForm(RecipeBookContrbutionForm):

    code_check = forms.IntegerField(label="Passcode", help_text="Enter the passcode provided in your confirmation email.")

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
    
    def clean_code_check(self):
        if self.cleaned_data.get("code_check") != self.instance.code:
            raise ValidationError("Code is invalid")
    
    def get_final_fields(self):
        final_fields = super().get_final_fields()
        return ["code_check", *final_fields]