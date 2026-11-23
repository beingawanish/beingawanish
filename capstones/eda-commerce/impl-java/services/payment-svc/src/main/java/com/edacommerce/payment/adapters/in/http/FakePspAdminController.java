package com.edacommerce.payment.adapters.in.http;

import com.edacommerce.payment.adapters.out.psp.fake.FakePsp;
import com.edacommerce.payment.adapters.out.psp.fake.FakePspConfig;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/** {@code GET/PUT /admin/fakes/psp} (admin.yaml): the chaos drills turn these knobs. */
@RestController
public class FakePspAdminController {
  private final FakePsp psp;

  public FakePspAdminController(FakePsp psp) {
    this.psp = psp;
  }

  @GetMapping("/admin/fakes/psp")
  public FakePspConfig get() {
    return psp.config();
  }

  /** Merges the given fields into the current behaviour; omitted fields keep their value. */
  @PutMapping("/admin/fakes/psp")
  public FakePspConfig put(@RequestBody FakePspConfig patch) {
    return psp.update(patch);
  }
}
