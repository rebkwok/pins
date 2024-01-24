from typing import Any
from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Hidden, HTML, Div, Field

from .models import RecipeBookSubmission, PAGE_TYPE_COSTS


class CustomFileInput(forms.widgets.ClearableFileInput):
    input_text = "Choose another"
    template_name = 'fundraising/widgets/image_file_input.html'


def _field_with_spinner_js(field_name):
    return Field(field_name, onfocus="document.getElementById('spinner').classList.remove('show');")


class RecipeBookContrbutionForm(forms.ModelForm):
    email1 = forms.EmailField(label="Email (again)")

    recipe_layout_fields = [
        HTML("<h2>Recipe Details</h2><hr>"),
        HTML(
            '<div class="alert-warning">'
            'Please take a look at the list of <a href="/fundraising/recipe-book/recipes" target="_blank">'
            'already submitted recipes here</a> and avoid submitting duplicates if possible!'
            '</div>'
        ),
        _field_with_spinner_js("title"),
        _field_with_spinner_js("category"),
        _field_with_spinner_js("preparation_time"), 
        _field_with_spinner_js("cook_time"), 
        _field_with_spinner_js("servings"), 
        _field_with_spinner_js("ingredients"), 
        Div(_field_with_spinner_js("method"), HTML("<span id='method_ch_count' class='help-block'>Character count: 0</span>")),
        HTML("<h2>Profile</h2><hr>"),
        _field_with_spinner_js("submitted_by"),
        _field_with_spinner_js("profile_image"),
        Div(_field_with_spinner_js("profile_caption"), HTML("<span id='profile_caption_ch_count' class='help-block'>Character count: 0</span>")),
    ]
    photo_layout_fields = [
        HTML(
            "<p class='text-danger'>Full page photos will be printed A4 size (if image quality allows), in portrait orientation. "
            "You are welcome to submit photos in any orientation, but be aware that we will need to crop them or "
            "or reduce the print size to fit the page.</p>"
        ),
        _field_with_spinner_js("photo"), 
        _field_with_spinner_js("photo_title"), 
        _field_with_spinner_js("photo_caption")
    ]
    layout_fields_by_page_type = {
        "single": recipe_layout_fields,
        "single_with_facing": [*recipe_layout_fields, HTML("<h2>Facing Full-Page Photo</h2><hr>"), *photo_layout_fields],
        "double": recipe_layout_fields + [
            HTML("<h2>Additional Photo on second page (optional)</h2><hr>"),
            _field_with_spinner_js("photo")
        ],
        "photo": [HTML("<h2>Full-Page Photo</h2><hr>"), *photo_layout_fields],
    }

    recipe_required =[
        "title", "category", "preparation_time", "cook_time", "servings", "ingredients", "method",
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
        layout_fields = self.layout_fields_by_page_type.get(page_type, [])
        
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
            _field_with_spinner_js("name"),
            _field_with_spinner_js("email"),
            _field_with_spinner_js("email1"),
            HTML(
               "<span class='help-block'>Choose your page type:</span>"
               "<ul class='help-block'>"
               "<li>Single page recipe: A recipe on one page, with a small profile photo</li>"
               "<li>Double page recipe: A longer recipe that won't fit on a single one page, "
               "with method continuing to a second page, a small profile photo, and an optional additional photo on the second page</li>"
               "<li>Single page recipe with full page facing photo: recipe on one page, with small profile photo, and full-page photo on the opposite page</li>"
               "<li>Photo page only: no recipe, full-page photo with title/caption</li>"
               "</ul>"
               "<span class='help-block'>See example pages <a href='https://podencosinneed.org/fundraising-recipe-book/'>here.</a></span>"
            ),
            _field_with_spinner_js("page_type"),
        ]

    def get_final_fields(self):
        return [
            Submit('submit', "Submit", onclick="document.getElementById('spinner').classList.add('show');"),
            HTML(
                '<div class="alert-success" id="spinner">'
                '<div class="lds-ellipsis">'
                    '<div></div>'
                    '<div></div>'
                    '<div></div>'
                    '<div></div>'
                '</div>'
                '<small>Uploading photos may take a minute or two, please wait.</small>'
                '</div>'
                )
        ]
    
    def clean_email1(self):
        if self.cleaned_data["email"] != self.cleaned_data["email1"]:
            raise ValidationError("Email fields do not match")

    class Meta:
        model = RecipeBookSubmission
        fields = [
            "name", "email",
            "page_type",
            "title", "category", "preparation_time", "cook_time", "servings", "ingredients", "method",
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
            Hidden("email1", self.instance.email),
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
        return [_field_with_spinner_js("code_check"), *final_fields]
