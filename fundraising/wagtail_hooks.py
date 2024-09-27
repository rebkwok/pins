from django.urls import path, reverse

from wagtail import hooks
from wagtail.admin.ui.tables import BooleanColumn
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup
from wagtail.admin.filters import WagtailFilterSet
from wagtail.admin.views.bulk_action import BulkAction
from wagtail.admin.panels import FieldPanel, TabbedInterface, ObjectList, InlinePanel
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem

from django_filters.filters import ChoiceFilter

from .admin_views import auctions_index, auction_detail, auction_docs, auction_item_log
from .models import RecipeBookSubmission, AuctionCategory, Bid, Auction, AuctionItemLog
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
    add_to_settings_menu = True


from django.db.models import Max, Q

class BidFilterSet(WagtailFilterSet):

    auction = ChoiceFilter(choices=Auction.objects.values_list("id", "title"), method="filter_by_auction", label="Auction")
    limit_to = ChoiceFilter(choices=(("all", "All bids"), ("winning", "Winning bids only")), method="filter_by_limit_to", label="Limit to")


    class Meta:
        model = Bid
        fields = [
            "auction",
            "auction_item",
        ]
    
    def filter_by_auction(self, queryset, name, value):
        auction_item_ids = Auction.objects.get(id=value).get_children().specific().values_list('id', flat=True)
        return queryset.filter(auction_item__id__in=auction_item_ids)

    def filter_by_limit_to(self, queryset, name, value):
        if value == "winning":
            max_bids = queryset.values('auction_item').annotate(max_bid=Max('amount')).order_by()
            q_statement = Q()
            for pair in max_bids:
                q_statement |= (Q(auction_item__id=pair['auction_item']) & Q(amount=pair['max_bid']))
            return queryset.filter(q_statement)
        return queryset


class BidViewSet(SnippetViewSet):
    model = Bid
    # template_prefix = "bid_"
    list_display = (
        "auction_item", "user", "amount", "placed_at"
    )
    fields = ("auction_item", "user", "amount")
    filterset_class = BidFilterSet

    handler = TabbedInterface([
        ObjectList(
            [
                FieldPanel("auction_item"), 
                FieldPanel("user"),
                FieldPanel("amount"),
            ],
            heading='Bid Details'
        ),
    ])


class AuctionItemLogViewSet(SnippetViewSet):
    model = AuctionItemLog
    list_display = (
        "timestamp", "log", "auction_item"
    )
    fields = ("timestamp", "log", "auction_item")

    filterset_class = BidFilterSet


@hooks.register('register_admin_urls')
def register_auction_url():
    return [
        path('auctions/', auctions_index, name='auctions'),
        path('auction/<pk>', auction_detail, name='auction_detail'),
        path('auctions/docs/', auction_docs, name='auction_docs'),
        path('auction/log/<pk>/', auction_item_log, name='auction_item_log'),
    ]


@hooks.register('register_admin_menu_item')
def register_auction_menu_item():
    submenu = Menu(items=[
        MenuItem('Auction Categories', reverse(AuctionCategoryViewSet().get_url_name("list")), icon_name='tablet-alt'),
        MenuItem('Auctions', reverse('auctions'), icon_name='tablet-alt'),
    ])

    return SubmenuMenuItem('Auctions', submenu, icon_name='hammer')


@hooks.register('register_admin_menu_item')
def register_auction_docs_menu_item():
    return MenuItem('Auctions help', reverse('auction_docs'), icon_name='page', order=1000)


register_snippet(RecipeBookGroup)
register_snippet(AuctionCategoryViewSet)
