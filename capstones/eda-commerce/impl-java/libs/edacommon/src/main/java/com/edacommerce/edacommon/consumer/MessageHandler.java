package com.edacommerce.edacommon.consumer;

import com.edacommerce.edacommon.envelope.MessageContext;
import org.apache.avro.specific.SpecificRecord;

/**
 * Handles one message type, identified by its Avro full name (the {@code ce_type} header). Services
 * declare handlers as Spring beans; the consumer runtime registers them by type. The handler runs
 * inside the runtime's database transaction, after the inbox insert; anything it appends to the
 * outbox commits atomically with its business change.
 */
public interface MessageHandler<T extends SpecificRecord> {

  /** The generated class this handler reads with (its reader schema). */
  Class<T> messageType();

  void handle(T message, MessageContext context);

  default String typeName() {
    return org.apache.avro.specific.SpecificData.get().getSchema(messageType()).getFullName();
  }
}
