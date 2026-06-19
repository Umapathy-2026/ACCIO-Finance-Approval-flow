# ACCIO UI Refactor Changelog

**Date:** 18 June 2026  
**Component:** Requester Dashboard - Navigation & Layout  
**Files Modified:** 2

---

## Summary of Changes

Refactored the requester dashboard navigation to eliminate duplicate "Request History" tabs and align the sidebar navigation pattern with the Admin "All Tickets" page for a cleaner, more consistent user experience.

---

## Files Modified

### 1. `app/templates/base.html`

**Change:** Reordered sidebar navigation items for regular users (role='user')

**Before:**
```html
<!-- Request History appeared first -->
<a href="{{ url_for('req.dashboard') }}?tab=history" class="nav-item ...">
    <i data-lucide="clock"></i> Request History
</a>
<a href="{{ url_for('req.dashboard') }}" class="nav-item ...">
    <i data-lucide="ticket"></i> My Requests
</a>
```

**After:**
```html
<!-- My Requests appears first, Request History second -->
<a href="{{ url_for('req.dashboard') }}" class="nav-item ...">
    <i data-lucide="ticket"></i> My Requests
</a>
<a href="{{ url_for('req.dashboard') }}?view=history" class="nav-item ...">
    <i data-lucide="clock"></i> Request History
</a>
```

**Details:**
- Swapped order: "My Requests" now appears first, "Request History" second
- Updated query parameter from `?tab=history` to `?view=history` for consistency
- Updated active state logic to use `request.args.get('view')` instead of `request.args.get('tab')`

---

### 2. `app/templates/requester/dashboard.html`

**Change:** Removed in-page tab bar and implemented view-based rendering

**Before:**
- Page contained a tab bar with "My Requests" and "Request History" tabs
- Both views rendered in the same page with JavaScript tab switching
- Duplicate navigation (sidebar + tabs)

**After:**
- Tab bar completely removed
- Page uses `request.args.get('view', 'my_requests')` to determine which view to render
- Each view renders as a standalone clean page
- No duplicate tabs anywhere in the UI

**Implementation Details:**
```jinja2
{% set view = request.args.get('view', 'my_requests') %}

{% if view == 'history' %}
<!-- Request History View (standalone page) -->
{% else %}
<!-- My Requests View (standalone page) -->
{% endif %}
```

**Features Preserved:**
- Search, filter, sort, and pagination for both views
- All existing JavaScript functionality intact
- Ticket status badges and color coding maintained
- Copy ticket number functionality preserved

---

## User Experience Improvements

### Before
- ❌ "Request History" appeared twice (sidebar + main page tabs)
- ❌ Sidebar order was reversed (Request History → My Requests)
- ❌ Inconsistent with Admin "All Tickets" page pattern

### After
- ✅ "Request History" appears only in sidebar
- ✅ Sidebar order matches user workflow (My Requests → Request History)
- ✅ Consistent with Admin "All Tickets" page pattern
- ✅ Clean, single-purpose pages for each view
- ✅ No redundant navigation elements

---

## Navigation Flow

### My Requests (Default View)
- **URL:** `/dashboard` or `/dashboard?view=my_requests`
- **Sidebar:** "My Requests" (active state)
- **Content:** Active tickets (Pending, Under Review, Needs Clarification)
- **Filters:** Status dropdown (Pending, Under Review, Needs Clarification)

### Request History
- **URL:** `/dashboard?view=history`
- **Sidebar:** "Request History" (active state)
- **Content:** Resolved tickets (Approved, Rejected, Sent to Fulfilment)
- **Filters:** Status dropdown + date range picker

---

## Technical Notes

- No backend changes required (Python routes unchanged)
- All changes are frontend-only (HTML/Jinja2 templates)
- JavaScript functionality fully preserved
- No database migrations needed
- Backward compatible with existing ticket data

---

## Testing Checklist

- [x] Sidebar displays "My Requests" first, "Request History" second
- [x] Clicking "My Requests" shows only active tickets
- [x] Clicking "Request History" shows only resolved tickets
- [x] No duplicate tabs appear on either page
- [x] Search functionality works on both views
- [x] Filter functionality works on both views
- [x] Sort functionality works on both views
- [x] Pagination works on "My Requests" view
- [x] Active state highlighting works correctly in sidebar
- [x] Ticket detail navigation works from both views
- [x] Copy ticket number functionality works
- [x] Responsive design maintained

---

## Related Files (No Changes Required)

- `app/routes/requester.py` - No changes needed
- `app/models.py` - No changes needed
- `app/static/` - No changes needed
- All other template files - No changes needed

---

## Deployment Notes

This is a frontend-only change. To deploy:

1. Update `app/templates/base.html`
2. Update `app/templates/requester/dashboard.html`
3. No database migrations required
4. No environment variable changes needed
5. No Python code changes required
6. Restart application server

**Estimated deployment time:** < 5 minutes  
**Risk level:** Low (frontend-only, no backend changes)  
**Rollback:** Revert the two template files to previous versions