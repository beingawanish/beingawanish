package com.edacommerce.edacommon.autoconfigure;

import java.util.List;
import org.springframework.boot.context.properties.bind.Bindable;
import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.context.annotation.Condition;
import org.springframework.context.annotation.ConditionContext;
import org.springframework.core.type.AnnotatedTypeMetadata;

/**
 * True when {@code eda.consumer.enabled} (default true) and {@code eda.consumer.topics} is
 * non-empty. A placeholder expression cannot see a YAML list (it binds as topics[0], topics[1],
 * ...), so the condition binds the list properly.
 */
class OnConsumerTopicsCondition implements Condition {
  @Override
  public boolean matches(ConditionContext context, AnnotatedTypeMetadata metadata) {
    Binder binder = Binder.get(context.getEnvironment());
    boolean enabled = binder.bind("eda.consumer.enabled", Boolean.class).orElse(Boolean.TRUE);
    List<String> topics =
        binder.bind("eda.consumer.topics", Bindable.listOf(String.class)).orElse(List.of());
    return enabled && !topics.isEmpty();
  }
}
