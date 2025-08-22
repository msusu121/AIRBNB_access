document.addEventListener("htmx:afterOnLoad", function(evt) {
  try{
    const data = JSON.parse(evt.detail.xhr.responseText);
    const box = document.getElementById("result");
    if (!box || !data) return;

    if(!data.ok){
      box.innerHTML = `<div class="text-red-700">${data.error||'Error'}</div>`;
      return;
    }
    if(data.decision === "allow"){
      const i = data.info;
      box.innerHTML = `
        <div class="space-y-2">
          <div class="text-green-700 font-semibold">ACCESS: ALLOW</div>
          <div class="text-sm">Guest: <b>${i.guest_name}</b> (${i.national_id})</div>
          <div class="text-sm">Property: <b>${i.property}</b></div>
          <div class="text-sm">Room: <b>${i.room}</b></div>
          <div class="text-sm">Stay: ${new Date(i.check_in).toLocaleString()} → ${new Date(i.check_out).toLocaleString()}</div>
          <div class="text-sm">Guests: ${i.guests_count}</div>
          <div class="text-sm">Vehicle: ${i.owns_vehicle ? (i.vehicle_plate || 'Yes') : 'No'}</div>
          <div class="text-xs text-slate-500">Booking #${i.booking_id}</div>
        </div>`;
    } else {
      box.innerHTML = `<div class="text-amber-700 font-semibold">ACCESS: NO ACTIVE BOOKING</div>
        <p class="text-sm text-slate-600 mt-2">No valid booking found for the captured/entered ID. Consider manual verification.</p>`;
    }
  }catch(e){
    // Non-JSON: ignore — server may have returned HTML
  }
});
