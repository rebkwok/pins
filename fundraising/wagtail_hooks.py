from wagtail import hooks
from wagtail.admin.ui.tables import BooleanColumn
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup
from wagtail.admin.views.bulk_action import BulkAction
from wagtail.admin.panels import Panel, FieldPanel, TabbedInterface, ObjectList

from wagtail_modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register


from .models import RecipeBookSubmission, AuctionCategory
from paypal.standard.ipn.models import PayPalIPN


# ensure our modeladmin is created
class RecipeBookSubmissionViewSet(SnippetViewSet):
    model = RecipeBookSubmission
    template_prefix = "recipe_book_"
    list_display = (
        "reference", "date_submitted", "name", "page_type_verbose",
        "title", "category", "formatted_cost",
        BooleanColumn("paid"), "status"
    )
    search_fields = ("name", "title")
    list_filter = ["paid", "processing", "complete"]
    list_export = (
            "reference", 
            "date_submitted", 
            "name", 
            "email",
            "page_type",
            "category", 
            "cost", 
            "paid",
            "date_paid",
            "processing",
            "complete",
            "title",
            "preparation_time",
            "cook_time",
            "servings",
            "ingredients",
            "method",
            "submitted_by",
            "profile_image",
            "profile_caption",
            "photo",
            "photo_title",
            "photo_caption",
    )
    menu_order = 400
    icon = "tablet-alt"

    submission_panels = [
        FieldPanel('name'),
        FieldPanel('email'),
        FieldPanel('page_type'),
        FieldPanel('date_submitted'),
        FieldPanel('paid'),
        FieldPanel('date_paid'),
        FieldPanel('processing'),
        FieldPanel('complete'),
    ]
    recipe_panels = [
        FieldPanel('title'),
        FieldPanel('category'),
        FieldPanel('preparation_time'),
        FieldPanel('cook_time'),
        FieldPanel('servings'),
        FieldPanel('ingredients'),
        FieldPanel('method'),
        
    ]
    profile_panels = [
        FieldPanel('submitted_by'),
        FieldPanel('profile_image'),
        FieldPanel('profile_caption'),
    ]
    photo_panels = [
        FieldPanel('photo'),
        FieldPanel('photo_title'),
        FieldPanel('photo_caption'),
    ]

    edit_handler = TabbedInterface([
        ObjectList(submission_panels, heading='Submission Details'),
        ObjectList(recipe_panels, heading='Recipe Details'),
        ObjectList(profile_panels, heading='Profile'),
        ObjectList(photo_panels, heading='Photo Details'),
    ])


class PayPalIPNViewSet(SnippetViewSet):
    model = PayPalIPN
    list_display = ("invoice", "txn_id", "payment_status", "payment_date", BooleanColumn("flag"), "flag_info")
    search_fields = ("invoice",)
    fields = ("invoice", "payment_status", "flag", "flag_info")    
    edit_handler = TabbedInterface([
        ObjectList(
            [
                FieldPanel("invoice"),
                FieldPanel("txn_id"),
                FieldPanel("txn_type"),
                FieldPanel("payment_date"),
                FieldPanel("payment_status"),
                FieldPanel("mc_gross"),
                FieldPanel("mc_fee"),
                FieldPanel("mc_currency"),
            ], 
            heading='Payment Details'
        ),
        ObjectList(
            [
                FieldPanel("flag"), 
                FieldPanel("flag_info"),
            ],
            heading='Flag info'
        ),
        ObjectList(
            [
                FieldPanel("first_name"), 
                FieldPanel("last_name"),
                FieldPanel("payer_email"),
                FieldPanel("item_name"), 
            ],
            heading='Buyer & Item'
        ),
    ])


class RecipeBookGroup(SnippetViewSetGroup):
    menu_label = "Recipe Book"
    menu_icon = "tablet-alt"
    items = (RecipeBookSubmissionViewSet, PayPalIPNViewSet)
    menu_order = 200


@hooks.register("register_bulk_action")
class MarkPaid(BulkAction):
    display_name = "Mark paid"
    action_type = "action"
    aria_label = "Mark submission as paid"
    models = [RecipeBookSubmission]  # list of models the action should execute upon
    template_name = "fundraising/admin/update_confirmation.html"

    @classmethod
    def execute_action(cls, objects, **kwargs):
        count = len(objects)
        for object in objects:
            object.paid = True
            object.save()
        return count, count  # return the count of updated objects


@hooks.register("register_bulk_action")
class MarkProcessing(BulkAction):
    display_name = "Mark processing"
    action_type = "action1"
    aria_label = "Mark submission as processing"
    models = [RecipeBookSubmission]  # list of models the action should execute upon
    template_name = "fundraising/admin/update_confirmation.html"

    @classmethod
    def execute_action(cls, objects, **kwargs):
        count = 0
        for object in objects:
            if object.paid:
                object.processing = True
                object.save()
                count += 1
        return count, count  # return the count of updated objects


@hooks.register("register_bulk_action")
class MarkComplete(BulkAction):
    display_name = "Mark complete"
    action_type = "action2"
    aria_label = "Mark submission as completed"
    models = [RecipeBookSubmission]  # list of models the action should execute upon
    template_name = "fundraising/admin/update_confirmation.html"

    @classmethod
    def execute_action(cls, objects, **kwargs):
        count = 0
        for object in objects:
            if object.paid:
                object.processing = True
                object.complete = True
                object.save()
                count += 1
        return count, count  # return the count of updated objects


class AuctionCategoryViewSet(SnippetViewSet):
    model = AuctionCategory
    list_display = (
        "name",
    )


register_snippet(RecipeBookGroup)
register_snippet(AuctionCategory)
