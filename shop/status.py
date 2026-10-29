
from salesman.orders.status import BaseOrderStatus


class OrderStatus(BaseOrderStatus):
    """
    Salesman's order statuses (see salesman.orders.status.OrderStatus), with
    PARTIALLY_SHIPPED: some, but not all, of the items that need shipping have
    been shipped (or collected).
    """

    NEW = "NEW", "New"  # Order with reference created, items are in the basket.
    CREATED = "CREATED", "Created"  # Created with items and pending payment.
    HOLD = "HOLD", "Hold"  # Stock reduced but still awaiting payment.
    FAILED = "FAILED", "Failed"  # Payment failed, retry is available.
    CANCELLED = "CANCELLED", "Cancelled"  # Cancelled by seller, stock increased.
    PROCESSING = "PROCESSING", "Processing"  # Payment confirmed, processing order.
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED", "Partially shipped"
    SHIPPED = "SHIPPED", "Shipped"  # Everything that needs shipping has been shipped.
    COMPLETED = "COMPLETED", "Completed"  # Completed and received by customer.
    REFUNDED = "REFUNDED", "Refunded"  # Fully refunded by seller.

    @classmethod
    def get_payable(cls):
        return [cls.CREATED, cls.HOLD, cls.FAILED]

    @classmethod
    def get_transitions(cls):
        return {
            "NEW": [cls.CREATED],
            "CREATED": [cls.HOLD, cls.FAILED, cls.CANCELLED, cls.PROCESSING],
            "HOLD": [cls.FAILED, cls.CANCELLED, cls.PROCESSING],
            "FAILED": [cls.CANCELLED, cls.PROCESSING],
            "CANCELLED": [],
            "PROCESSING": [
                cls.PARTIALLY_SHIPPED,
                cls.SHIPPED,
                cls.COMPLETED,
                cls.REFUNDED,
            ],
            "PARTIALLY_SHIPPED": [cls.SHIPPED, cls.COMPLETED, cls.REFUNDED],
            "SHIPPED": [cls.COMPLETED, cls.REFUNDED],
            "COMPLETED": [cls.REFUNDED],
            "REFUNDED": [],
        }
