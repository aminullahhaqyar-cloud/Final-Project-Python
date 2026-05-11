// Auto-dismiss alerts after 4 seconds
document.addEventListener('DOMContentLoaded', () => {
  const alerts = document.querySelectorAll('.alert');
  alerts.forEach(alert => {
    setTimeout(() => {
      alert.style.transition = 'opacity .5s';
      alert.style.opacity = '0';
      setTimeout(() => alert.remove(), 500);
    }, 4000);
  });

  // Set minimum due date to tomorrow for checkout forms
  const dueDateInputs = document.querySelectorAll('input[name="due_date"]');
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const minDate = tomorrow.toISOString().split('T')[0];
  dueDateInputs.forEach(input => {
    input.min = minDate;
    if (!input.value) {
      // Default due date = 14 days from now
      const defaultDue = new Date();
      defaultDue.setDate(defaultDue.getDate() + 14);
      input.value = defaultDue.toISOString().split('T')[0];
    }
  });

  // Highlight overdue rows
  document.querySelectorAll('.overdue-row').forEach(row => {
    row.title = 'This book is overdue';
  });
});
