document.addEventListener("DOMContentLoaded", function () {

```
const form = document.getElementById("taskForm");

form.addEventListener("submit", function (event) {

    event.preventDefault();

    alert("✅ JavaScript is working! Page will NOT refresh.");

    console.log("Form submission prevented successfully.");

});
```

});
