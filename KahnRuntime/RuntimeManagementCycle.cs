using System;

namespace KahnRuntime
{
    internal static class RuntimeManagementCycle
    {
        // Protection validates its own managed-position facts; new-risk recovery cannot starve it.
        public static bool Run(Func<bool> reconcile, Func<bool> protect,
            Action observe, Action<bool> evaluate)
        {
            bool reconciled = reconcile();
            bool protectedPosition = protect();
            observe();
            evaluate(reconciled && protectedPosition);
            bool finalReconciled = reconcile();
            bool finalProtected = protect();
            return finalReconciled && finalProtected;
        }
    }
}
