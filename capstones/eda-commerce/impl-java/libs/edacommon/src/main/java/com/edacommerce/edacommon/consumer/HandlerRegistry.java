package com.edacommerce.edacommon.consumer;

import java.util.Collection;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import org.springframework.lang.Nullable;

/** ce_type -> handler. Dispatch happens on the header, before any deserialisation (guide §4). */
public class HandlerRegistry {
  private final Map<String, MessageHandler<?>> handlers = new HashMap<>();

  public HandlerRegistry(Collection<? extends MessageHandler<?>> all) {
    for (MessageHandler<?> handler : all) {
      MessageHandler<?> previous = handlers.put(handler.typeName(), handler);
      if (previous != null) {
        throw new IllegalStateException("two handlers for " + handler.typeName());
      }
    }
  }

  @Nullable
  public MessageHandler<?> get(String type) {
    return handlers.get(type);
  }

  public Set<String> types() {
    return Set.copyOf(handlers.keySet());
  }

  public boolean isEmpty() {
    return handlers.isEmpty();
  }
}
