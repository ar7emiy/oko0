### The whole pipeline as one function

`run_pipeline` chains steps 2-16 on two validated input frames and returns every table. The
Run section below calls the steps one by one so each prints its own output; the self-tests
call this function on small inputs.