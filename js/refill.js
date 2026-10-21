(function(){

  /* ================= WHERE SUBMISSIONS GO =================
     Same setup as the transfer form — paste your endpoint here.
     Must be covered by a signed BAA: refill requests contain a
     name, date of birth and medication details, which is PHI.
  ========================================================= */
  var LOADED_AT = Date.now();
  var ENDPOINT = "https://script.google.com/macros/s/AKfycbx2bGFmpqFiCUEKHxy26hsO1JZsFxx4Mcz2ZkH-NYRyUCkxQkHqecpbkvE09DG7NdPdDg/exec";

  var TOTAL = 4, cur = 1;
  var steps    = document.querySelectorAll('.step');
  var backBtn  = document.getElementById('backBtn');
  var progWrap = document.getElementById('progWrap');
  var progFill = document.getElementById('progFill');
  var progLabel= document.getElementById('progLabel');
  var progTime = document.getElementById('progTime');
  var TIMES = {1:'About 30 seconds', 2:'About 20 seconds left', 3:'Almost there', 4:'One click to go'};

  function val(id){ var e=document.getElementById(id); return e ? (e.value||'').trim() : ''; }
  function method(){ return document.querySelector('input[name="method"]:checked').value; }
  function isDelivery(){ return method() === 'Delivery'; }

  function show(n){
    cur = n;
    for (var i=0;i<steps.length;i++) steps[i].classList.toggle('on', +steps[i].dataset.step === n);
    var finished = n > TOTAL;
    progWrap.style.display = finished ? 'none' : '';
    backBtn.hidden = (n === 1 || finished);
    if (!finished){
      progFill.style.width = (n / TOTAL * 100) + '%';
      progLabel.textContent = 'Step ' + n + ' of ' + TOTAL;
      progTime.textContent = TIMES[n] || '';
      var f = steps[n-1].querySelector('input:not([type=radio]):not([type=checkbox]),textarea,select');
      if (f) setTimeout(function(){ f.focus(); }, 60);
    }
    window.scrollTo({top:0, behavior:'smooth'});
  }

  function flag(id, errId, bad){
    var el=document.getElementById(id), er=errId?document.getElementById(errId):null;
    if (el) el.classList.toggle('bad', bad);
    if (er) er.classList.toggle('on', bad);
    return !bad;
  }

  function validate(n){
    if (n === 1){
      var nameOk = !!val('fname') && !!val('lname');
      var dobOk  = !!val('dob');
      var phOk   = val('phone').replace(/\D/g,'').length >= 10;
      flag('fname',null,!val('fname')); flag('lname',null,!val('lname'));
      document.getElementById('nameErr').classList.toggle('on', !nameOk);
      flag('dob','dobErr',!dobOk);
      flag('phone','phoneErr',!phOk);
      return nameOk && dobOk && phOk;
    }
    if (n === 2) return flag('rx','rxErr', !val('rx'));
    if (n === 3){
      if (isDelivery() && !flag('addr','addrErr', !val('addr'))) return false;
      buildReview();
      return true;
    }
    return true;
  }

  function esc(t){ return String(t).replace(/[<>&]/g,function(c){
    return {'<':'&lt;','>':'&gt;','&':'&amp;'}[c]; }); }

  function buildReview(){
    var what = val('rx');
    var where = isDelivery()
      ? (val('addr') + (val('city') ? '\\n' + val('city') : '') + (val('zip') ? ' ' + val('zip') : ''))
      : 'Pick up in store';
    var rows = [
      ['Refilling',   what],
      ['Patient',     val('fname') + ' ' + val('lname')],
      ['Date of birth', val('dob')],
      ['Phone',       val('phone')],
      ['Email',       val('email') || '—'],
      [isDelivery() ? 'Deliver to' : 'Collection', where]
    ];
    if (val('notes')) rows.push(['Notes', val('notes')]);
    var html='';
    for (var i=0;i<rows.length;i++)
      html += '<div class="rrow"><span class="k">'+rows[i][0]+
              '</span><span class="v">'+esc(rows[i][1])+'</span></div>';
    document.getElementById('review').innerHTML = html;
  }

  // --- "I don't have my Rx number" reveals the medication field ---

  // --- pickup hides the address block ---
  var radios = document.querySelectorAll('input[name="method"]');
  for (var i=0;i<radios.length;i++){
    radios[i].addEventListener('change', function(){
      document.getElementById('cDeliver').classList.toggle('sel', isDelivery());
      document.getElementById('cPickup').classList.toggle('sel', !isDelivery());
      document.getElementById('addrWrap').classList.toggle('hidden', !isDelivery());
      document.getElementById('lastStep').textContent = isDelivery()
        ? 'Free delivery to your door'
        : 'Pick it up at the counter — no waiting';
    });
  }

  // --- navigation ---
  document.addEventListener('click', function(e){
    var n = e.target.closest('[data-next]');
    if (n && validate(cur)) show(cur + 1);
  });
  backBtn.addEventListener('click', function(){ if (cur > 1) show(cur - 1); });
  document.addEventListener('keydown', function(e){
    if (e.key !== 'Enter' || e.target.tagName === 'TEXTAREA') return;
    if (cur <= 3){ e.preventDefault(); if (validate(cur)) show(cur + 1); }
  });
  document.addEventListener('input', function(e){
    e.target.classList.remove('bad');
    var box = e.target.closest('.step');
    if (box){ var er = box.querySelectorAll('.err.on');
      for (var i=0;i<er.length;i++) er[i].classList.remove('on'); }
  });
  var zipEl = document.getElementById('zip');
  zipEl.addEventListener('input', function(e){ e.target.value = e.target.value.replace(/\D/g,''); });

  document.getElementById('consent').addEventListener('change', function(){
    document.getElementById('consentBox').classList.remove('bad');
    document.getElementById('consentErr').classList.remove('on');
  });

  // --- submit ---
  var submitBtn = document.getElementById('submitBtn');
  submitBtn.addEventListener('click', function(){
    if (!document.getElementById('consent').checked){
      document.getElementById('consentBox').classList.add('bad');
      document.getElementById('consentErr').classList.add('on');
      return;
    }

    var payload = {
      type: 'refill',
        hp: (document.getElementById('hpCompany')||{}).value || '',
        elapsed: Date.now() - LOADED_AT,
        token: 'mhrx-web-2026',
      medications: val('rx'),
      firstName: val('fname'), lastName: val('lname'), dob: val('dob'),
      phone: val('phone'), email: val('email'),
      method: method(),
      address: isDelivery() ? val('addr') : '',
      city:    isDelivery() ? val('city') : '',
      zip:     isDelivery() ? val('zip')  : '',
      notes: val('notes'),
      smsConsent: document.getElementById('smsConsent').checked,
      smsConsentText: document.getElementById('smsConsent').checked
        ? 'Agreed to SMS terms at ' + new Date().toISOString() : '',
      submittedAt: new Date().toISOString()
    };

    if (!ENDPOINT){
      console.log('Refill request (demo — set ENDPOINT to send):', payload);
      show(TOTAL + 1);
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending…';

    fetch(ENDPOINT, {
      method: 'POST',
      headers: {'Content-Type':'text/plain;charset=utf-8'},   // avoids CORS preflight
      body: JSON.stringify(payload)
    })
    .then(function(r){ if (!r.ok) throw new Error('HTTP '+r.status); show(TOTAL + 1); })
    .catch(function(err){
      console.error('Submit failed:', err);
      submitBtn.disabled = false;
      submitBtn.textContent = 'Send my refill request';
      var box = document.getElementById('consentErr');
      box.textContent = "Sorry — that didn't go through. Please call us at (516) 304-5038 and we'll take it over the phone.";
      box.classList.add('on');
    });
  });

  show(1);
})();
