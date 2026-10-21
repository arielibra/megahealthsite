(function(){

  /* ================= WHERE SUBMISSIONS GO =================
     Paste the endpoint from your form provider between the quotes.
     Leave it empty and the form stays in demo mode (logs to console).

     Using Google Workspace? Deploy google-apps-script.gs as a Web app
     and paste its URL here. That script writes each request to a Google
     Sheet and emails you an alert containing no patient detail.

     Whatever you use must be covered by a signed BAA — this form
     collects medication names tied to a named person, which is PHI.
  ========================================================= */
  var LOADED_AT = Date.now();
  var ENDPOINT = "https://script.google.com/macros/s/AKfycbx2bGFmpqFiCUEKHxy26hsO1JZsFxx4Mcz2ZkH-NYRyUCkxQkHqecpbkvE09DG7NdPdDg/exec";

  var TOTAL = 4;
  var cur = 1;

  var steps     = document.querySelectorAll('.step');
  var backBtn   = document.getElementById('backBtn');
  var progWrap  = document.getElementById('progWrap');
  var progFill  = document.getElementById('progFill');
  var progLabel = document.getElementById('progLabel');
  var progTime  = document.getElementById('progTime');

  var TIMES = {1:'About 60 seconds', 2:'About 40 seconds left', 3:'Almost there', 4:'One click to go'};

  function show(n){
    cur = n;
    for (var i=0;i<steps.length;i++){
      steps[i].classList.toggle('on', +steps[i].dataset.step === n);
    }
    var finished = n > TOTAL;
    progWrap.style.display = finished ? 'none' : '';
    backBtn.hidden = (n === 1 || finished);

    if (!finished){
      progFill.style.width = (n / TOTAL * 100) + '%';
      progLabel.textContent = 'Step ' + n + ' of ' + TOTAL;
      progTime.textContent = TIMES[n] || '';
      var focusable = steps[n-1].querySelector('input,textarea,select');
      if (focusable) setTimeout(function(){ focusable.focus(); }, 60);
    }
    window.scrollTo({top:0, behavior:'smooth'});
  }

  function val(id){ return (document.getElementById(id).value || '').trim(); }

  function flag(id, errId, bad){
    var el = document.getElementById(id);
    var er = errId ? document.getElementById(errId) : null;
    if (el) el.classList.toggle('bad', bad);
    if (er) er.classList.toggle('on', bad);
    return !bad;
  }

  /* -----------------------------------------------------------------
     DELIVERY AREA — free delivery anywhere in NYC.
     Keyed on the first 3 digits of the ZIP. Edit this map to change
     coverage; anything not listed still goes through, it just gets a
     softer message instead of a delivery promise.
  ----------------------------------------------------------------- */
  var AREAS = {
    '100':'Manhattan','101':'Manhattan','102':'Manhattan',
    '104':'the Bronx',
    '112':'Brooklyn',
    '111':'Queens','113':'Queens','114':'Queens','116':'Queens',
    '103':'Staten Island',
    '110':'Nassau County','115':'Nassau County'   // remove these two if you only cover the 5 boroughs
  };

  function areaFor(zip){ return AREAS[zip.slice(0,3)] || null; }

  // per-step validation — returns true if the step may advance
  function validate(n){
    if (n === 1){
      var zip = val('zip');
      var ok = /^\d{5}$/.test(zip);
      flag('zip','zipErr',!ok);
      if (!ok) return false;

      var area = areaFor(zip);
      document.getElementById('zipEcho').textContent = area || zip;
      if (area){
        document.getElementById('areaHead').innerHTML =
          'Good news &mdash; we deliver to <span>' + area + '</span>.';
        document.getElementById('areaSub').textContent =
          'Free delivery, same day in most cases.';
      } else {
        // outside the mapped area — still let them through, just don't promise
        document.getElementById('areaHead').textContent = 'Thanks — we got your ZIP (' + zip + ').';
        document.getElementById('areaSub').textContent =
          "We'll confirm delivery options for your address when we call. You can always pick up in store.";
      }
      return true;
    }
    if (n === 2){
      var nameOk  = !!val('fname') && !!val('lname');
      var dobOk   = !!val('dob');
      var phoneOk = val('phone').replace(/\D/g,'').length >= 10;
      flag('fname', null, !val('fname'));
      flag('lname', null, !val('lname'));
      document.getElementById('nameErr').classList.toggle('on', !nameOk);
      flag('dob','dobErr', !dobOk);
      flag('phone','phoneErr', !phoneOk);
      return nameOk && dobOk && phoneOk;
    }
    if (n === 3){
      var pOk = flag('pharmacy','pharmErr', !val('pharmacy'));
      var fOk = flag('pharmPhone','pharmPhoneErr', val('pharmPhone').replace(/\D/g,'').length < 10);
      var mOk = flag('meds','medsErr', !val('meds'));
      if (pOk && fOk && mOk) buildReview();
      return pOk && fOk && mOk;
    }
    return true;
  }

  function buildReview(){
    var rows = [
      ['ZIP code',        val('zip')],
      ['Current pharmacy',val('pharmacy') + (val('pharmPhone') ? '\n' + val('pharmPhone') : '')],
      ['Medications',     val('meds')],
      ['Name',            val('fname') + ' ' + val('lname')],
      ['Date of birth',   val('dob')],
      ['Phone',           val('phone')],
      ['Email',           val('email') || '—'],
      ['Best time',       document.getElementById('best').value]
    ];
    var html = '';
    for (var i=0;i<rows.length;i++){
      html += '<div class="rrow"><span class="k">' + rows[i][0] +
              '</span><span class="v">' + String(rows[i][1]).replace(/[<>&]/g, function(c){
                return {'<':'&lt;','>':'&gt;','&':'&amp;'}[c];
              }) + '</span></div>';
    }
    document.getElementById('review').innerHTML = html;
  }

  // ---- navigation ----
  document.addEventListener('click', function(e){
    var next = e.target.closest('[data-next]');
    if (next && validate(cur)) show(cur + 1);
  });

  backBtn.addEventListener('click', function(){ if (cur > 1) show(cur - 1); });

  // Enter advances (except inside the textarea)
  document.addEventListener('keydown', function(e){
    if (e.key !== 'Enter' || e.target.tagName === 'TEXTAREA') return;
    if (cur <= 3){ e.preventDefault(); if (validate(cur)) show(cur + 1); }
  });

  // clear error styling as soon as they start fixing it
  document.addEventListener('input', function(e){
    e.target.classList.remove('bad');
    var box = e.target.closest('.step');
    if (box) { var er = box.querySelectorAll('.err.on');
      for (var i=0;i<er.length;i++) er[i].classList.remove('on'); }
  });

  // digits only in the ZIP box
  document.getElementById('zip').addEventListener('input', function(e){
    e.target.value = e.target.value.replace(/\D/g,'');
  });

  document.getElementById('consent').addEventListener('change', function(){
    document.getElementById('consentBox').classList.remove('bad');
    document.getElementById('consentErr').classList.remove('on');
  });

  // ---- submit ----
  var submitBtn = document.getElementById('submitBtn');

  function submitFailed(){
    submitBtn.disabled = false;
    submitBtn.textContent = 'Send my request';
    var box = document.getElementById('consentErr');
    box.textContent = "Sorry — that didn't go through. Please call us at (516) 304-5038 and we'll take your details over the phone.";
    box.classList.add('on');
  }

  submitBtn.addEventListener('click', function(){
    if (!document.getElementById('consent').checked){
      document.getElementById('consentBox').classList.add('bad');
      document.getElementById('consentErr').textContent =
        "Please check the box so we're allowed to call your pharmacy.";
      document.getElementById('consentErr').classList.add('on');
      return;
    }

    var payload = {
      type: 'transfer',
        hp: (document.getElementById('hpCompany')||{}).value || '',
        elapsed: Date.now() - LOADED_AT,
        token: 'mhrx-web-2026',
      zip: val('zip'), pharmacy: val('pharmacy'), pharmacyPhone: val('pharmPhone'),
      medications: val('meds'), firstName: val('fname'), lastName: val('lname'),
        dob: val('dob'),
      phone: val('phone'), email: val('email'),
      bestTime: document.getElementById('best').value,
      smsConsent: document.getElementById('smsConsent').checked,
      smsConsentText: document.getElementById('smsConsent').checked
        ? 'Agreed to SMS terms at ' + new Date().toISOString() : '',
      deliveryArea: areaFor(val('zip')) || 'outside mapped area',
      submittedAt: new Date().toISOString()
    };

    // demo mode — no endpoint configured yet
    if (!ENDPOINT){
      console.log('Transfer request (demo — set ENDPOINT to send):', payload);
      show(TOTAL + 1);
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending…';

    fetch(ENDPOINT, {
      method: 'POST',
      // text/plain avoids a CORS preflight, which Google Apps Script
      // web apps do not answer. Body is still JSON.
      headers: {'Content-Type':'text/plain;charset=utf-8'},
      body: JSON.stringify(payload)
    })
    .then(function(r){
      if (!r.ok) throw new Error('HTTP ' + r.status);
      show(TOTAL + 1);          // only celebrate once it actually landed
    })
    .catch(function(err){
      console.error('Submit failed:', err);
      submitFailed();           // never tell a patient it worked when it did not
    });
  });

  show(1);
})();
