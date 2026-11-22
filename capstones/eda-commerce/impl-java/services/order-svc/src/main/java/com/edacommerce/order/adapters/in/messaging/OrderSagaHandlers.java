package com.edacommerce.order.adapters.in.messaging;

import com.edacommerce.common.ShipmentDirection;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.fulfilment.FulfilmentAccepted;
import com.edacommerce.fulfilment.FulfilmentCancelled;
import com.edacommerce.fulfilment.FulfilmentFailed;
import com.edacommerce.fulfilment.OrderDispatched;
import com.edacommerce.fulfilment.OrderPacked;
import com.edacommerce.inventory.ReservationCommitted;
import com.edacommerce.inventory.ReservationExpired;
import com.edacommerce.inventory.ReservationReleased;
import com.edacommerce.inventory.StockReservationRejected;
import com.edacommerce.inventory.StockReserved;
import com.edacommerce.kernel.Money;
import com.edacommerce.order.application.OrderSagaService;
import com.edacommerce.order.domain.OrderSagaTrigger;
import com.edacommerce.payment.PaymentAuthorized;
import com.edacommerce.payment.PaymentCaptureFailed;
import com.edacommerce.payment.PaymentCaptured;
import com.edacommerce.payment.PaymentDeclined;
import com.edacommerce.payment.PaymentVoided;
import com.edacommerce.shipping.ShipmentCreated;
import com.edacommerce.shipping.ShipmentDelivered;
import com.edacommerce.shipping.ShipmentException;
import com.edacommerce.shipping.ShipmentExceptionCode;
import java.util.List;

/**
 * Every reply and event the order saga listens to, as (message type -> trigger) mappings. Types not
 * listed here (OrderPicked, ShipmentInTransit, refunds, returns intake) are ignored by the runtime.
 */
public final class OrderSagaHandlers {
  private OrderSagaHandlers() {}

  public static List<MessageHandler<?>> all(OrderSagaService s) {
    return List.of(
        new SagaTriggerHandler<>(StockReserved.class, StockReserved::getOrderId, m -> new OrderSagaTrigger.StockReserved(m.getReservationId()), s),
        new SagaTriggerHandler<>(StockReservationRejected.class, StockReservationRejected::getOrderId,
            m -> new OrderSagaTrigger.StockReservationRejected(m.getReservationId()), s),
        new SagaTriggerHandler<>(ReservationCommitted.class, ReservationCommitted::getOrderId,
            m -> new OrderSagaTrigger.ReservationCommitted(m.getReservationId()), s),
        new SagaTriggerHandler<>(ReservationReleased.class, ReservationReleased::getOrderId,
            m -> new OrderSagaTrigger.ReservationReleased(m.getReservationId()), s),
        new SagaTriggerHandler<>(ReservationExpired.class, ReservationExpired::getOrderId,
            m -> new OrderSagaTrigger.ReservationExpired(m.getReservationId()), s),
        new SagaTriggerHandler<>(PaymentAuthorized.class, PaymentAuthorized::getOrderId,
            m -> new OrderSagaTrigger.PaymentAuthorized(m.getPaymentId(), m.getAuthorizationExpiresAt()), s),
        new SagaTriggerHandler<>(PaymentDeclined.class, PaymentDeclined::getOrderId,
            m -> new OrderSagaTrigger.PaymentDeclined(m.getPaymentId(), m.getReason().name()), s),
        new SagaTriggerHandler<>(PaymentVoided.class, PaymentVoided::getOrderId, m -> new OrderSagaTrigger.PaymentVoided(m.getPaymentId()), s),
        new SagaTriggerHandler<>(PaymentCaptured.class, PaymentCaptured::getOrderId,
            m -> new OrderSagaTrigger.PaymentCaptured(m.getPaymentId(), Money.of(m.getAmount().getAmountMinor(), m.getAmount().getCurrency())), s),
        new SagaTriggerHandler<>(PaymentCaptureFailed.class, PaymentCaptureFailed::getOrderId,
            m -> new OrderSagaTrigger.PaymentCaptureFailed(m.getPaymentId(), m.getReason().name(), m.getRetryable()), s),
        new SagaTriggerHandler<>(FulfilmentAccepted.class, FulfilmentAccepted::getOrderId,
            m -> new OrderSagaTrigger.FulfilmentAccepted(m.getFulfilmentId()), s),
        new SagaTriggerHandler<>(OrderPacked.class, OrderPacked::getOrderId, m -> new OrderSagaTrigger.OrderPacked(m.getFulfilmentId()), s),
        new SagaTriggerHandler<>(OrderDispatched.class, OrderDispatched::getOrderId,
            m -> new OrderSagaTrigger.OrderDispatched(m.getFulfilmentId(), m.getShipmentId()), s),
        new SagaTriggerHandler<>(FulfilmentFailed.class, FulfilmentFailed::getOrderId,
            m -> new OrderSagaTrigger.FulfilmentFailed(m.getFulfilmentId(), m.getReason().name()), s),
        new SagaTriggerHandler<>(FulfilmentCancelled.class, FulfilmentCancelled::getOrderId,
            m -> new OrderSagaTrigger.FulfilmentCancelled(m.getFulfilmentId()), s),
        new SagaTriggerHandler<>(ShipmentCreated.class, ShipmentCreated::getOrderId,
            m -> new OrderSagaTrigger.ShipmentCreated(m.getShipmentId(), m.getDirection() == ShipmentDirection.OUTBOUND, m.getCarrier(), m.getTrackingNumber()), s),
        new SagaTriggerHandler<>(ShipmentDelivered.class, ShipmentDelivered::getOrderId,
            m -> new OrderSagaTrigger.ShipmentDelivered(m.getShipmentId(), m.getDirection() == ShipmentDirection.OUTBOUND, m.getDeliveredAt()), s),
        new SagaTriggerHandler<>(ShipmentException.class, ShipmentException::getOrderId,
            m -> new OrderSagaTrigger.ShipmentException(m.getShipmentId(), m.getDirection() == ShipmentDirection.OUTBOUND,
                m.getCode() == ShipmentExceptionCode.LOST, m.getCode().name()), s));
  }
}
